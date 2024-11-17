import argparse
import io
import json
import logging
import os
import queue
import re
import shutil
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from threading import Lock
from tkinter import filedialog, scrolledtext, ttk
from typing import Any, Dict

import requests


class IORedirector(io.StringIO):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def write(self, string):
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        self.text_widget.update()

    def flush(self):
        pass


class ProcessingMode:
    FILE_ORGANIZER = "File Organizer"
    FOLDER_MERGER = "Folder Merger"

    @staticmethod
    def get_tooltip(mode: str) -> str:
        tooltips = {
            ProcessingMode.FILE_ORGANIZER: "Organizes individual 3DSky files into categorized folders",
            ProcessingMode.FOLDER_MERGER: "Merges pre-organized 3DSky folders while updating folder summaries",
        }
        return tooltips.get(mode, "")


class CreateToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20

        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")

        label = ttk.Label(
            self.tooltip,
            text=self.text,
            justify="left",
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
        )
        label.pack()

    def hide_tooltip(self, event=None):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


class SkyFileOrganizerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("3DSky File Organizer")
        self.root.geometry("800x600")

        # Set icon (if available)
        try:
            if getattr(sys, "frozen", False):
                application_path = sys._MEIPASS
            else:
                application_path = os.path.dirname(os.path.abspath(__file__))
            icon_path = os.path.join(application_path, "icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass  # Skip if icon not found

        self.source_var = tk.StringVar()
        self.dest_var = tk.StringVar()
        self.progress_var = tk.StringVar(value="Ready to start...")
        self.mode_var = tk.StringVar(value=ProcessingMode.FILE_ORGANIZER)
        self.is_running = False

        self.setup_gui()

    def setup_gui(self):
        # Create main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Mode selection
        mode_frame = ttk.LabelFrame(main_frame, text="Processing Mode", padding="5")
        mode_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        for i, mode in enumerate(
            [ProcessingMode.FILE_ORGANIZER, ProcessingMode.FOLDER_MERGER]
        ):
            rb = ttk.Radiobutton(
                mode_frame, text=mode, value=mode, variable=self.mode_var
            )
            rb.grid(row=0, column=i, padx=10)
            CreateToolTip(rb, ProcessingMode.get_tooltip(mode))

        # Source directory selection
        ttk.Label(main_frame, text="Source Directory:").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        ttk.Entry(main_frame, textvariable=self.source_var, width=50).grid(
            row=1, column=1, padx=5, sticky=tk.W + tk.E
        )
        ttk.Button(main_frame, text="Browse", command=self.browse_source).grid(
            row=1, column=2, padx=5
        )

        # Destination directory selection
        ttk.Label(main_frame, text="Destination Directory:").grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        ttk.Entry(main_frame, textvariable=self.dest_var, width=50).grid(
            row=2, column=1, padx=5, sticky=tk.W + tk.E
        )
        ttk.Button(main_frame, text="Browse", command=self.browse_dest).grid(
            row=2, column=2, padx=5
        )

        # Progress information
        ttk.Label(main_frame, text="Progress:").grid(
            row=3, column=0, sticky=tk.W, pady=5
        )
        ttk.Label(main_frame, textvariable=self.progress_var).grid(
            row=3, column=1, columnspan=2, sticky=tk.W, pady=5
        )

        # Console output
        console_frame = ttk.LabelFrame(main_frame, text="Console Output", padding="5")
        console_frame.grid(
            row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5
        )
        main_frame.rowconfigure(4, weight=1)
        main_frame.columnconfigure(1, weight=1)

        self.console = scrolledtext.ScrolledText(
            console_frame, wrap=tk.WORD, width=70, height=20
        )
        self.console.pack(fill=tk.BOTH, expand=True)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=3, pady=10)

        self.start_button = ttk.Button(
            button_frame, text="Start Processing", command=self.start_processing
        )
        self.start_button.pack(side=tk.LEFT, padx=5)

        ttk.Button(button_frame, text="Exit", command=self.root.quit).pack(
            side=tk.LEFT, padx=5
        )

    def browse_source(self):
        directory = filedialog.askdirectory()
        if directory:
            self.source_var.set(directory)

    def browse_dest(self):
        directory = filedialog.askdirectory()
        if directory:
            self.dest_var.set(directory)

    def start_processing(self):
        if self.is_running:
            return

        source_dir = self.source_var.get()
        dest_dir = self.dest_var.get()

        if not source_dir or not dest_dir:
            self.console.insert(
                tk.END, "❌ Please select both source and destination directories.\n"
            )
            return

        if not os.path.exists(source_dir) or not os.path.exists(dest_dir):
            self.console.insert(tk.END, "❌ One or both directories do not exist.\n")
            return

        # Disable the start button and update status
        self.start_button.configure(state="disabled")
        self.is_running = True
        self.progress_var.set("Processing...")

        # Redirect stdout to our console
        sys.stdout = IORedirector(self.console)

        # Start processing in a separate thread
        thread = threading.Thread(
            target=self.run_processor, args=(source_dir, dest_dir, self.mode_var.get())
        )
        thread.daemon = True
        thread.start()

    def run_processor(self, source_dir, dest_dir, mode):
        try:
            organizer = SkyFileOrganizer(source_dir, dest_dir)
            if mode == ProcessingMode.FILE_ORGANIZER:
                organizer.process_files()
            else:
                organizer.merge_folders()
        except Exception as e:
            self.console.insert(tk.END, f"\n❌ Error: {str(e)}\n")
        finally:
            self.is_running = False
            self.start_button.configure(state="normal")
            self.progress_var.set("Processing complete!")
            sys.stdout = sys.__stdout__


class SkyFileOrganizer:
    def __init__(
        self, source_directory=None, destination_directory=None, max_workers=5
    ):
        self.source_directory = source_directory
        self.destination_directory = destination_directory
        self.max_workers = max_workers
        self.models_root = None
        self.api_url = "https://3dsky.org/api/models"
        self.image_base_url = (
            "https://b6.3ddd.ru/media/cache/tuk_model_custom_filter_ang_en/"
        )
        self.not_found_log = "not_found_models.json"
        self.not_found_files = {}
        self.not_found_lock = Lock()  # Lock for thread-safe dict access
        self.print_lock = Lock()  # Lock for thread-safe printing
        self.processing_queue = queue.Queue()
        self.processed_count = 0  # Add counter for processed files
        self.total_files = 0  # Add total files counter
        self.counter_lock = Lock()  # Add lock for thread-safe counting
        self.threads = []
        self.setup_logging()

    def safe_print(self, *args, **kwargs):
        """Thread-safe printing"""
        with self.print_lock:
            print(*args, **kwargs)

    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            filename="3dsky_organizer.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        self.logger = logging

    def merge_folders(self):
        """Merge pre-organized folders from source to destination"""
        source_dir, dest_dir = self.get_directories()

        if not os.path.exists(os.path.join(source_dir, "3ds_models")):
            self.safe_print("❌ Source directory does not contain a 3ds_models folder")
            return

        source_models_dir = os.path.join(source_dir, "3ds_models")
        dest_models_dir = os.path.join(dest_dir, "3ds_models")

        if not os.path.exists(dest_models_dir):
            os.makedirs(dest_models_dir)

        self.safe_print("\n🔄 Starting folder merge process...")

        # Walk through all categories in source
        for root, dirs, files in os.walk(source_models_dir):
            relative_path = os.path.relpath(root, source_models_dir)
            dest_path = os.path.join(dest_models_dir, relative_path)

            # Create destination directory if it doesn't exist
            if not os.path.exists(dest_path):
                os.makedirs(dest_path)
                self.safe_print(f"📁 Created directory: {relative_path}")

            # First, remove any existing summary files
            summary_path = os.path.join(root, "folder_summary.json")
            if os.path.exists(summary_path):
                try:
                    os.remove(summary_path)
                    self.safe_print(f"🗑️ Removed old summary file from: {relative_path}")
                except Exception as e:
                    self.safe_print(f"❌ Error removing summary file: {str(e)}")

            # Move all files
            for file in files:
                if file == "folder_summary.json":
                    continue  # Skip summary files, they should be deleted already

                source_file = os.path.join(root, file)
                dest_file = os.path.join(dest_path, file)

                if os.path.exists(dest_file):
                    self.safe_print(f"⚠️ File already exists, skipping: {file}")
                    continue

                try:
                    shutil.move(source_file, dest_file)
                    self.safe_print(f"✅ Moved: {file}")
                except Exception as e:
                    self.safe_print(f"❌ Error moving {file}: {str(e)}")

            # Update folder summary for current directory
            self.update_folder_summary(dest_path)

        # Clean up empty directories in source
        self.cleanup_empty_dirs(source_models_dir)

        # Update all folder summaries from bottom up
        self.update_all_folder_summaries(dest_models_dir)
        self.safe_print("\n✨ Folder merge complete!")

    def cleanup_empty_dirs(self, directory):
        """Recursively remove empty directories"""
        for root, dirs, files in os.walk(directory, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    os.rmdir(dir_path)
                    self.safe_print(f"🗑️ Removed empty directory: {dir_path}")
                except OSError:
                    # Directory not empty, skip it
                    pass

        # Try to remove the root directory itself if empty
        try:
            os.rmdir(directory)
            self.safe_print(f"🗑️ Removed empty root directory: {directory}")
        except OSError:
            pass

    def update_all_folder_summaries(self, start_path):
        """Update folder summaries for all directories from bottom up"""
        for root, dirs, files in os.walk(start_path, topdown=False):
            self.update_folder_summary(root)

    def process_files(self):
        """Process all files using multiple threads"""
        source_dir, dest_dir = self.get_directories()
        if not os.path.exists(source_dir):
            self.safe_print(f"❌ Error: Source directory {source_dir} does not exist")
            self.logger.error(f"Source directory {source_dir} does not exist")
            return
        if not os.path.exists(dest_dir):
            self.safe_print(
                f"❌ Error: Destination directory {dest_dir} does not exist"
            )
            self.logger.error(f"Destination directory {dest_dir} does not exist")
            return

        # Get all compressed files
        compressed_files = [
            f
            for f in os.listdir(source_dir)
            if f.lower().endswith((".zip", ".rar", ".7z"))
        ]

        self.total_files = len(compressed_files)
        self.safe_print(f"\n🔍 Found {self.total_files} compressed files to process")

        # Initialize worker threads
        for i in range(self.max_workers):
            thread = threading.Thread(
                target=self.worker, args=(self.total_files,), name=f"Worker-{i+1}"
            )
            thread.daemon = True
            thread.start()
            self.threads.append(thread)

        # Add files to processing queue
        for filename in compressed_files:
            self.processing_queue.put(filename)

        # Add sentinel values to signal threads to exit
        for _ in range(self.max_workers):
            self.processing_queue.put(None)

        # Wait for all threads to complete
        for thread in self.threads:
            thread.join()

        # Write not found files to JSON in the destination directory
        not_found_log_path = os.path.join(self.models_root, self.not_found_log)
        if self.not_found_files:
            self.safe_print(
                f"\n⚠️ Writing {len(self.not_found_files)} not found files to log"
            )
            with open(not_found_log_path, "w", encoding="utf-8") as f:
                json.dump(self.not_found_files, f, indent=4)
            self.logger.info(f"Wrote not found files to {not_found_log_path}")

        # Update root directory summary
        self.update_folder_summary(self.models_root)
        self.safe_print("\n✨ Processing complete!")

    def worker(self, total_files):
        """Worker thread to process files"""
        processed_count = 0
        while True:
            filename = self.processing_queue.get()
            if filename is None:  # Check for sentinel value
                self.processing_queue.task_done()
                break

            try:
                with self.counter_lock:
                    self.processed_count += 1
                    current_count = self.processed_count
                self.safe_print(
                    f"\n📦 Processing file {current_count}/{total_files}: {filename}"
                )
                self.process_single_file(filename)
            except Exception as e:
                self.safe_print(f"❌ Error processing {filename}: {str(e)}")
                self.logger.error(f"Error processing {filename}: {str(e)}")
            finally:
                self.processing_queue.task_done()
                # Add small delay to avoid overwhelming the API
                time.sleep(1)

    def process_single_file(self, filename):
        """Process a single file"""
        file_id = self.extract_file_id(filename)
        if not file_id:
            self.safe_print(f"⚠️ Invalid filename format: {filename}")
            self.logger.warning(f"Invalid filename format: {filename}")
            with self.not_found_lock:
                self.not_found_files[filename] = "Invalid filename format"
            return

        # Get model details from API
        details = self.get_model_details(file_id)
        if not details:
            return

        # Log successful find
        self.logger.info(f"Found model: {details['title']} for file: {filename}")

        # Create folder structure
        destination_folder = self.create_folder_structure(details["categories"])

        # Move the compressed file
        source_path = os.path.join(self.source_directory, filename)
        dest_path = os.path.join(destination_folder, filename)

        try:
            self.safe_print(
                f"📦 Moving file to: {os.path.basename(destination_folder)}"
            )
            shutil.move(source_path, dest_path)
            self.safe_print("✅ File moved successfully")
            self.logger.info(f"Moved file to: {dest_path}")
        except Exception as e:
            self.safe_print(f"❌ Error moving file: {str(e)}")
            self.logger.error(f"Error moving file {filename}: {str(e)}")
            return

        # Handle images
        self.handle_images(file_id, destination_folder, details)

        # Update folder summary
        self.update_folder_summary(destination_folder)

    def handle_images(self, file_id, destination_folder, details):
        """Handle downloading new image and moving existing images"""
        # First try to download new image
        image_path = os.path.join(destination_folder, f"{file_id}.jpeg")
        download_success = self.download_image(details["image_url"], image_path)

        if download_success:
            # If download successful, remove any existing images
            self.remove_existing_images(destination_folder, file_id)
            self.logger.info(f"Downloaded new image for {file_id}")
        else:
            # If download failed, move existing images
            self.move_related_images(self.source_directory, destination_folder, file_id)

    def remove_existing_images(self, folder, file_id):
        """Remove existing images if new download is successful"""
        image_extensions = [".jpg", ".jpeg", ".png"]
        model_number = file_id.split(".")[0]

        for filename in os.listdir(folder):
            file_base, ext = os.path.splitext(filename)
            if ext.lower() in image_extensions and file_base.startswith(model_number):
                try:
                    os.remove(os.path.join(folder, filename))
                    self.logger.info(f"Removed existing image: {filename}")
                except Exception as e:
                    self.logger.error(
                        f"Error removing existing image {filename}: {str(e)}"
                    )

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
        """Update folder summary JSON file with accurate subfolder counting"""
        print(f"\nUpdating folder summary for: {folder_path}")
        summary = {
            "total_files": 0,
            "total_subfolders": 0,
            "file_types": {},
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Get immediate subfolders
        immediate_subfolders = [
            d
            for d in os.listdir(folder_path)
            if os.path.isdir(os.path.join(folder_path, d))
        ]
        summary["total_subfolders"] = len(immediate_subfolders)

        # Count files only in current directory
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            if os.path.isfile(item_path) and item != "folder_summary.json":
                summary["total_files"] += 1
                ext = os.path.splitext(item)[1].lower()
                summary["file_types"][ext] = summary["file_types"].get(ext, 0) + 1

        # Write summary to JSON file
        summary_path = os.path.join(folder_path, "folder_summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=4)

        print(
            f"📊 Summary updated for {os.path.basename(folder_path)}: "
            f"{summary['total_files']} files, "
            f"{summary['total_subfolders']} immediate subfolders"
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


def main():
    root = tk.Tk()
    app = SkyFileOrganizerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
