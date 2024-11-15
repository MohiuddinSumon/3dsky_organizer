import argparse
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

import requests


class SkyFileOrganizer:
    def __init__(self, source_directory=None, destination_directory=None):
        self.source_directory = source_directory
        self.destination_directory = destination_directory
        self.models_root = None  # Will store the path to 3ds_models folder
        self.setup_logging()
        self.api_url = "https://3dsky.org/api/models"
        self.image_base_url = (
            "https://b6.3ddd.ru/media/cache/tuk_model_custom_filter_ang_en/"
        )
        self.not_found_log = "not_found_models.json"
        self.not_found_files = {}

    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            filename="3dsky_organizer.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        self.logger = logging

    def get_directories(self):
        """Get source and destination directories if not provided"""
        if not self.source_directory:
            self.source_directory = input(
                "Please enter the source directory path containing the files: "
            ).strip()
            print(f"Source directory set to: {self.source_directory}")

        if not self.destination_directory:
            self.destination_directory = input(
                "Please enter the destination directory path: "
            ).strip()
            print(f"Destination directory set to: {self.destination_directory}")

        # Create 3ds_models folder in destination
        self.models_root = os.path.join(self.destination_directory, "3ds_models")
        if not os.path.exists(self.models_root):
            os.makedirs(self.models_root)
            print(f"Created 3ds_models directory at: {self.models_root}")
            self.logger.info(f"Created 3ds_models directory at: {self.models_root}")

        return self.source_directory, self.destination_directory

    def extract_file_id(self, filename):
        """Extract the file ID from filename"""
        base_name = os.path.splitext(filename)[0]
        if re.match(r"^\d+\.[a-f0-9]+$", base_name):
            return base_name
        return None

    def get_model_details(self, file_id):
        """Get model details from 3dsky.org API"""
        print(f"\nFetching details for model ID: {file_id}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
        }
        payload = {"query": file_id, "order": "relevance"}

        try:
            print("Making API request...")
            response = requests.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            if not data.get("data", {}).get("models"):
                print(f"❌ No models found for ID: {file_id}")
                self.logger.error(
                    f"No models found in API response for file_id: {file_id}"
                )
                self.not_found_files[file_id] = "No models found in API response"
                return None

            model = data["data"]["models"][0]
            print(f"✅ Found model: {model.get('title_en', 'Untitled')}")

            # Get category information
            categories = []
            if model.get("category_parent"):
                categories.append(model["category_parent"]["title_en"])
            if model.get("category"):
                categories.append(model["category"]["title_en"])

            if not categories:
                print(f"❌ No categories found for model: {file_id}")
                self.logger.error(f"No categories found for model: {file_id}")
                self.not_found_files[file_id] = "No categories found"
                return None

            # Find matching image
            image_path = None
            for image in model.get("images", []):
                if image.get("file_name", "").startswith(file_id.split(".")[0]):
                    image_path = image.get("web_path")
                    break

            if not image_path:
                print(f"⚠️ No matching image found for model: {file_id}")
                self.logger.error(f"No matching image found for model: {file_id}")
                return None

            image_url = f"{self.image_base_url}{image_path}"

            return {
                "categories": categories,
                "image_url": image_url,
                "title": model.get("title_en"),
            }

        except Exception as e:
            print(f"❌ Error getting details for {file_id}: {str(e)}")
            self.logger.error(f"Error getting details for {file_id}: {str(e)}")
            self.not_found_files[file_id] = str(e)
            return None

    def create_folder_structure(self, categories):
        """Create folder structure based on categories"""
        current_path = self.models_root  # Start from 3ds_models folder
        for category in categories:
            # Clean category name for folder creation
            clean_category = re.sub(r'[<>:"/\\|?*]', "", category)
            current_path = os.path.join(current_path, clean_category)
            if not os.path.exists(current_path):
                os.makedirs(current_path)
                print(f"📁 Created category folder: {clean_category}")
        return current_path

    def download_image(self, image_url, destination):
        """Download image from URL"""
        print("📥 Downloading preview image...")
        try:
            response = requests.get(image_url, stream=True)
            response.raise_for_status()

            with open(destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print("✅ Image downloaded successfully")
            return True
        except Exception as e:
            print(f"❌ Error downloading image: {str(e)}")
            self.logger.error(f"Error downloading image {image_url}: {str(e)}")
            return False

    def update_folder_summary(self, folder_path):
        """Update folder summary JSON file"""
        print("\nUpdating folder summary...")
        summary = {
            "total_files": 0,
            "total_subfolders": 0,
            "file_types": {},
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Count all files and subfolders
        for root, dirs, files in os.walk(folder_path):
            summary["total_subfolders"] += len(dirs)
            for file in files:
                if file != "folder_summary.json":
                    summary["total_files"] += 1
                    ext = os.path.splitext(file)[1].lower()
                    summary["file_types"][ext] = summary["file_types"].get(ext, 0) + 1

        # Write summary to JSON file
        summary_path = os.path.join(folder_path, "folder_summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=4)

        print(
            f"📊 Summary updated: {summary['total_files']} files in {summary['total_subfolders']} subfolders"
        )
        return summary

    def move_related_images(self, source_dir, dest_dir, model_id):
        """Move any related image files to destination directory"""
        print("Looking for related images...")
        image_extensions = [".jpg", ".jpeg", ".png"]
        model_number = model_id.split(".")[0]
        moved_count = 0

        for filename in os.listdir(source_dir):
            file_base, ext = os.path.splitext(filename)
            if ext.lower() in image_extensions:
                if file_base.startswith(model_number):
                    source_path = os.path.join(source_dir, filename)
                    dest_path = os.path.join(dest_dir, filename)
                    try:
                        shutil.move(source_path, dest_path)
                        moved_count += 1
                        self.logger.info(
                            f"Moved related image: {filename} to {dest_dir}"
                        )
                    except Exception as e:
                        print(f"❌ Error moving image {filename}: {str(e)}")
                        self.logger.error(
                            f"Error moving related image {filename}: {str(e)}"
                        )

        if moved_count > 0:
            print(f"✅ Moved {moved_count} related images")
        else:
            print("ℹ️ No related images found")

    def process_files(self):
        """Process all files in the directory"""
        source_dir, dest_dir = self.get_directories()
        if not os.path.exists(source_dir):
            print(f"❌ Error: Source directory {source_dir} does not exist")
            self.logger.error(f"Source directory {source_dir} does not exist")
            return
        if not os.path.exists(dest_dir):
            print(f"❌ Error: Destination directory {dest_dir} does not exist")
            self.logger.error(f"Destination directory {dest_dir} does not exist")
            return

        # Get all compressed files
        compressed_files = [
            f
            for f in os.listdir(source_dir)
            if f.lower().endswith((".zip", ".rar", ".7z"))
        ]

        total_files = len(compressed_files)
        print(f"\n🔍 Found {total_files} compressed files to process")

        for index, filename in enumerate(compressed_files, 1):
            print(f"\n📦 Processing file {index}/{total_files}: {filename}")

            file_id = self.extract_file_id(filename)
            if not file_id:
                print(f"⚠️ Invalid filename format: {filename}")
                self.logger.warning(f"Invalid filename format: {filename}")
                self.not_found_files[filename] = "Invalid filename format"
                continue

            # Get model details from API
            details = self.get_model_details(file_id)
            if not details:
                continue  # Error already logged in get_model_details

            # Log successful find
            self.logger.info(f"Found model: {details['title']} for file: {filename}")

            # Create folder structure
            destination_folder = self.create_folder_structure(details["categories"])

            # Move the compressed file
            source_path = os.path.join(source_dir, filename)
            dest_path = os.path.join(destination_folder, filename)

            try:
                print(f"📦 Moving file to: {os.path.basename(destination_folder)}")
                shutil.move(source_path, dest_path)
                print("✅ File moved successfully")
                self.logger.info(f"Moved file to: {dest_path}")
            except Exception as e:
                print(f"❌ Error moving file: {str(e)}")
                self.logger.error(f"Error moving file {filename}: {str(e)}")
                continue

            # Move any related image files
            self.move_related_images(source_dir, destination_folder, file_id)

            # Download and save image
            image_path = os.path.join(destination_folder, f"{file_id}.jpeg")
            if self.download_image(details["image_url"], image_path):
                self.logger.info(f"Downloaded image to: {image_path}")

            # Update folder summary
            self.update_folder_summary(destination_folder)

            # Add delay to avoid overwhelming the server
            print("\n⏳ Waiting before processing next file...")
            time.sleep(1)

        # Write not found files to JSON in the destination directory
        not_found_log_path = os.path.join(self.models_root, self.not_found_log)
        if self.not_found_files:
            print(f"\n⚠️ Writing {len(self.not_found_files)} not found files to log")
            with open(not_found_log_path, "w", encoding="utf-8") as f:
                json.dump(self.not_found_files, f, indent=4)
            self.logger.info(f"Wrote not found files to {not_found_log_path}")

        # Update root directory summary
        self.update_folder_summary(self.models_root)
        print("\n✨ Processing complete!")


def main():
    parser = argparse.ArgumentParser(description="Organize 3dsky files into folders")
    parser.add_argument("--source", "-s", help="Source directory containing the files")
    parser.add_argument(
        "--destination", "-d", help="Destination directory for organized files"
    )
    args = parser.parse_args()

    print("🚀 Starting 3DSky File Organizer")
    organizer = SkyFileOrganizer(args.source, args.destination)
    organizer.process_files()


if __name__ == "__main__":
    main()
