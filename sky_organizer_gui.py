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
from PIL import Image


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
    FILE_COLLECTOR = "File Collector"
    DUPLICATE_FIXER = "Duplicate Fixer"
    SINGLE_FOLDER = "Single Folder"

    @staticmethod
    def get_tooltip(mode: str) -> str:
        tooltips = {
            ProcessingMode.FILE_ORGANIZER: "Organizes individual 3DSky files into categorized folders",
            ProcessingMode.FOLDER_MERGER: "Merges pre-organized 3DSky folders while updating folder summaries",
            ProcessingMode.FILE_COLLECTOR: "Collects all zip and image files from source directory and its subdirectories",
            ProcessingMode.DUPLICATE_FIXER: "Finds and fixes duplicate files by keeping the largest version and cleaning up names",
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
                # Set both the taskbar icon and the window icon
                # self.root.iconbitmap(default=icon_path)
                # self.root.iconbitmap(icon_path)
                # Create a PhotoImage object for the icon
                icon = tk.PhotoImage(file=icon_path)
                # Set both the taskbar icon and the window icon
                self.root.iconphoto(True, icon)
        except Exception:
            pass  # Skip if icon not found

        self.source_var = tk.StringVar()
        self.dest_var = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0)
        self.mode_var = tk.StringVar(value=ProcessingMode.FILE_ORGANIZER)
        self.is_running = False
        self.operation_var = tk.StringVar(value="move")
        self.download_preview_var = tk.BooleanVar(value=True)  # Default to True

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
            [
                ProcessingMode.FILE_ORGANIZER,
                ProcessingMode.FOLDER_MERGER,
                ProcessingMode.FILE_COLLECTOR,
                ProcessingMode.DUPLICATE_FIXER,
            ]
        ):
            rb = ttk.Radiobutton(
                mode_frame, text=mode, value=mode, variable=self.mode_var
            )
            rb.grid(row=0, column=i, padx=10)
            CreateToolTip(rb, ProcessingMode.get_tooltip(mode))

        # Add operation selection (after mode selection)
        self.operation_frame = ttk.LabelFrame(
            main_frame, text="Operation Type", padding="5"
        )
        self.operation_frame.grid(
            row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5
        )
        self.operation_frame.grid_remove()  # Hidden by default

        ttk.Radiobutton(
            self.operation_frame,
            text="Move Files",
            value="move",
            variable=self.operation_var,
        ).grid(row=0, column=0, padx=10)
        ttk.Radiobutton(
            self.operation_frame,
            text="Copy Files",
            value="copy",
            variable=self.operation_var,
        ).grid(row=0, column=1, padx=10)

        # Add preview download option after operation frame
        self.preview_frame = ttk.LabelFrame(
            main_frame, text="Preview Options", padding="5"
        )
        self.preview_frame.grid(
            row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5
        )

        ttk.Checkbutton(
            self.preview_frame,
            text="Download preview images from 3DSky",
            variable=self.download_preview_var,
        ).grid(row=0, column=0, padx=10)

        # Source directory selection
        ttk.Label(main_frame, text="Source Directory:").grid(
            row=3, column=0, sticky=tk.W, pady=5
        )
        ttk.Entry(main_frame, textvariable=self.source_var, width=50).grid(
            row=3, column=1, padx=5, sticky=tk.W + tk.E
        )
        ttk.Button(main_frame, text="Browse", command=self.browse_source).grid(
            row=3, column=2, padx=5
        )

        # Destination directory selection
        ttk.Label(main_frame, text="Destination Directory:").grid(
            row=4, column=0, sticky=tk.W, pady=5
        )
        ttk.Entry(main_frame, textvariable=self.dest_var, width=50).grid(
            row=4, column=1, padx=5, sticky=tk.W + tk.E
        )
        ttk.Button(main_frame, text="Browse", command=self.browse_dest).grid(
            row=4, column=2, padx=5
        )

        # Progress information
        progress_frame = ttk.LabelFrame(main_frame, text="Progress", padding="5")
        progress_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        # Add progress bar
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
            length=400,
        )
        self.progress_bar.grid(
            row=0, column=0, columnspan=2, padx=5, pady=5, sticky=(tk.W, tk.E)
        )

        # Add progress label below progress bar
        self.progress_label = ttk.Label(progress_frame, text="Ready to start...")
        self.progress_label.grid(row=1, column=0, columnspan=2, pady=2)

        # Add file count label
        self.file_count_label = ttk.Label(progress_frame, text="")
        self.file_count_label.grid(row=2, column=0, columnspan=2, pady=2)

        # Console output
        console_frame = ttk.LabelFrame(main_frame, text="Console Output", padding="5")
        console_frame.grid(
            row=6, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5
        )
        main_frame.rowconfigure(6, weight=1)
        main_frame.columnconfigure(1, weight=1)

        self.console = scrolledtext.ScrolledText(
            console_frame, wrap=tk.WORD, width=70, height=20
        )
        self.console.pack(fill=tk.BOTH, expand=True)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=7, column=0, columnspan=3, pady=10)

        self.start_button = ttk.Button(
            button_frame, text="Start Processing", command=self.start_processing
        )
        self.start_button.pack(side=tk.LEFT, padx=5)

        ttk.Button(button_frame, text="Exit", command=self.root.quit).pack(
            side=tk.LEFT, padx=5
        )

        # Add mode change handler
        self.mode_var.trace_add("write", self.on_mode_change)

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

        # Reset progress bar and labels
        self.progress_var.set(0)
        self.progress_label.config(text="Processing...")
        self.file_count_label.config(text="")

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
            organizer = SkyFileOrganizer(
                source_dir, dest_dir, download_previews=self.download_preview_var.get()
            )
            organizer.gui = self  # Store reference to GUI

            if mode == ProcessingMode.DUPLICATE_FIXER:
                organizer.fix_duplicates()
            elif mode == ProcessingMode.FILE_ORGANIZER:
                organizer.process_files()
            elif mode == ProcessingMode.FOLDER_MERGER:
                organizer.merge_folders(operation=self.operation_var.get())
            else:  # FILE_COLLECTOR
                organizer.collect_files()
        except Exception as e:
            self.console.insert(tk.END, f"\n❌ Error: {str(e)}\n")
        finally:
            self.is_running = False
            self.start_button.configure(state="normal")
            self.progress_var.set("Processing complete!")
            sys.stdout = sys.__stdout__

    def on_mode_change(self, *args):
        """Show/hide operation frame and preview frame based on selected mode"""
        # Show/hide operation frame
        if self.mode_var.get() == ProcessingMode.FOLDER_MERGER:
            self.operation_frame.grid()
        else:
            self.operation_frame.grid_remove()

        # Show/hide preview frame
        if self.mode_var.get() == ProcessingMode.FILE_ORGANIZER:
            self.preview_frame.grid()
        else:
            self.preview_frame.grid_remove()

    def update_progress(self, current, total, status_text=None):
        """Update progress bar and labels"""
        progress = (current / total * 100) if total > 0 else 0
        self.progress_var.set(progress)

        if status_text:
            self.progress_label.config(text=status_text)

        self.file_count_label.config(text=f"Processed {current} of {total} files")
        self.root.update_idletasks()


class SkyFileOrganizer:
    def __init__(
        self,
        source_directory=None,
        destination_directory=None,
        max_workers=5,
        download_previews=True,
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
        self.download_previews = download_previews
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

    def merge_folders(self, operation="move"):
        """Merge pre-organized folders from source to destination"""
        source_dir, dest_dir = self.get_directories()

        if not os.path.exists(os.path.join(source_dir, "3ds_models")):
            self.safe_print("❌ Source directory does not contain a 3ds_models folder")
            return

        source_models_dir = os.path.join(source_dir, "3ds_models")
        dest_models_dir = os.path.join(dest_dir, "3ds_models")

        if not os.path.exists(dest_models_dir):
            os.makedirs(dest_models_dir)

        self.safe_print(f"\n🔄 Starting folder {operation} process...")

        # Count total files first
        total_files = sum([len(files) for _, _, files in os.walk(source_models_dir)])
        processed_count = 0

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

            # Move/copy all files
            for file in files:
                if file == "folder_summary.json":
                    continue

                processed_count += 1
                if hasattr(self, "gui"):
                    self.gui.root.after(
                        0,
                        self.gui.update_progress,
                        processed_count,
                        total_files,
                        f"{operation.capitalize()}ing: {file}",
                    )

                source_file = os.path.join(root, file)
                dest_file = os.path.join(dest_path, file)

                if os.path.exists(dest_file):
                    self.safe_print(f"⚠️ File already exists, skipping: {file}")
                    continue

                try:
                    if operation == "move":
                        shutil.move(source_file, dest_file)
                    else:  # copy
                        shutil.copy2(source_file, dest_file)
                    self.safe_print(f"✅ {operation.capitalize()}d: {file}")
                except Exception as e:
                    self.safe_print(f"❌ Error {operation}ing {file}: {str(e)}")

            # Update folder summary for current directory
            self.update_folder_summary(dest_path)

        # Clean up empty directories in source if moving
        if operation == "move":
            self.cleanup_empty_dirs(source_models_dir)

        # Update all folder summaries from bottom up
        self.update_all_folder_summaries(dest_models_dir)

        # Update progress to complete
        if hasattr(self, "gui"):
            self.gui.root.after(
                0,
                self.gui.update_progress,
                total_files,
                total_files,
                "Folder merge complete!",
            )

        self.safe_print(f"\n✨ Folder {operation} complete!")

    def collect_files(self):
        """Collect all zip and image files from source directory and its subdirectories"""
        source_dir, dest_dir = self.get_directories()

        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)

        self.safe_print("\n🔍 Starting file collection process...")

        # Supported file extensions
        supported_extensions = {".zip", ".rar", ".7z", ".jpg", ".jpeg", ".png"}

        # First, count total files to process
        total_files = sum(
            1
            for root, _, files in os.walk(source_dir)
            for file in files
            if os.path.splitext(file)[1].lower() in supported_extensions
        )

        processed_count = 0

        # Walk through all subdirectories
        for root, _, files in os.walk(source_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in supported_extensions:
                    processed_count += 1
                    if hasattr(self, "gui"):
                        self.gui.root.after(
                            0,
                            self.gui.update_progress,
                            processed_count,
                            total_files,
                            f"Collecting: {file}",
                        )

                    source_file = os.path.join(root, file)
                    dest_file = os.path.join(dest_dir, file)

                    # Handle duplicate filenames
                    if os.path.exists(dest_file):
                        base, ext = os.path.splitext(file)
                        counter = 1
                        while os.path.exists(dest_file):
                            dest_file = os.path.join(dest_dir, f"{base}_{counter}{ext}")
                            counter += 1

                    try:
                        shutil.copy2(source_file, dest_file)
                        self.safe_print(f"✅ Copied: {file}")
                    except Exception as e:
                        self.safe_print(f"❌ Error copying {file}: {str(e)}")

        # Update progress to complete
        if hasattr(self, "gui"):
            self.gui.root.after(
                0,
                self.gui.update_progress,
                total_files,
                total_files,
                "File collection complete!",
            )

        self.safe_print("\n✨ File collection complete!")

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
        while True:
            filename = self.processing_queue.get()
            if filename is None:  # Check for sentinel value
                self.processing_queue.task_done()
                break

            try:
                with self.counter_lock:
                    self.processed_count += 1
                    current_count = self.processed_count

                # Update progress in GUI
                if hasattr(self, "gui"):
                    self.gui.root.after(
                        0,
                        self.gui.update_progress,
                        current_count,
                        total_files,
                        f"Processing: {filename}",
                    )

                self.safe_print(
                    f"\n📦 Processing file {current_count}/{total_files}: {filename}"
                )
                self.process_single_file(filename)
            except Exception as e:
                self.safe_print(f"❌ Error processing {filename}: {str(e)}")
                self.logger.error(f"Error processing {filename}: {str(e)}")
            finally:
                self.processing_queue.task_done()
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

        # First move all related files (zip and images) to destination
        self.safe_print(f"📦 Moving files to: {os.path.basename(destination_folder)}")

        # Move the compressed file first
        source_path = os.path.join(self.source_directory, filename)
        dest_path = os.path.join(destination_folder, filename)

        try:
            shutil.move(source_path, dest_path)
            self.safe_print("✅ Compressed file moved successfully")
            self.logger.info(f"Moved file to: {dest_path}")
        except Exception as e:
            self.safe_print(f"❌ Error moving compressed file: {str(e)}")
            self.logger.error(f"Error moving file {filename}: {str(e)}")
            return

        # Now attempt to download new image only if enabled
        if self.download_previews:
            image_path = os.path.join(destination_folder, f"{file_id}.jpeg")
            download_success = self.download_image(details["image_url"], image_path)

            if download_success:
                # Compare and keep only the best quality image
                self.handle_duplicate_images(destination_folder, file_id, image_path)
            else:
                self.safe_print(
                    "⚠️ Using existing images (if any) due to download failure"
                )
        else:
            # Just move existing images without downloading new ones
            self.move_related_images(self.source_directory, destination_folder, file_id)

        # Update folder summary after all files are in place
        self.update_folder_summary(destination_folder)

    def handle_duplicate_images(self, folder, file_id, new_image_path):
        """Compare and keep only the larger size image"""
        try:
            new_image = Image.open(new_image_path)
            new_image_size = os.path.getsize(new_image_path)
            new_image_resolution = new_image.size[0] * new_image.size[1]
            new_image.close()

            model_number = file_id.split(".")[0]
            existing_images = []

            # Collect information about existing images
            for filename in os.listdir(folder):
                if (
                    filename.lower().endswith((".jpg", ".jpeg", ".png"))
                    and filename.startswith(model_number)
                    and os.path.join(folder, filename) != new_image_path
                ):
                    try:
                        img_path = os.path.join(folder, filename)
                        img = Image.open(img_path)
                        resolution = img.size[0] * img.size[1]
                        size = os.path.getsize(img_path)
                        img.close()
                        existing_images.append(
                            {"path": img_path, "resolution": resolution, "size": size}
                        )
                    except Exception as e:
                        self.safe_print(
                            f"⚠️ Error processing image {filename}: {str(e)}"
                        )

            # Keep only the best quality image
            if existing_images:
                # Compare based on resolution first, then file size
                best_existing = max(
                    existing_images, key=lambda x: (x["resolution"], x["size"])
                )

                if best_existing["resolution"] > new_image_resolution or (
                    best_existing["resolution"] == new_image_resolution
                    and best_existing["size"] > new_image_size
                ):
                    # Existing image is better, remove the new one
                    os.remove(new_image_path)
                    self.safe_print("📸 Kept existing higher quality image")
                else:
                    # New image is better, remove all existing ones
                    for img in existing_images:
                        os.remove(img["path"])
                    self.safe_print("📸 Replaced with higher quality downloaded image")
            else:
                self.safe_print("📸 Kept newly downloaded image (no existing images)")

        except Exception as e:
            self.safe_print(f"⚠️ Error comparing images: {str(e)}")

    def remove_existing_images(self, folder, file_id):
        """Remove existing images if new download is successful"""
        image_extensions = [".jpg", ".jpeg", ".png"]
        model_number = file_id.split(".")[0]
        removed_count = 0

        for filename in os.listdir(folder):
            file_base, ext = os.path.splitext(filename)
            if (
                ext.lower() in image_extensions
                and file_base.startswith(model_number)
                and filename != f"{file_id}.jpeg"
            ):  # Don't remove the newly downloaded image
                try:
                    os.remove(os.path.join(folder, filename))
                    removed_count += 1
                    self.logger.info(f"Removed existing image: {filename}")
                except Exception as e:
                    self.logger.error(
                        f"Error removing existing image {filename}: {str(e)}"
                    )

        if removed_count > 0:
            print(f"🗑️ Removed {removed_count} older images")

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
        """Download image from URL with proper error handling and timeout"""
        print("📥 Downloading preview image...")
        try:
            # Set a timeout for the request
            response = requests.get(image_url, stream=True, timeout=30)
            response.raise_for_status()

            with open(destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print("✅ Image downloaded successfully")
            return True
        except requests.exceptions.Timeout:
            print("⚠️ Download timed out")
            self.logger.error(f"Timeout downloading image {image_url}")
            return False
        except requests.exceptions.RequestException as e:
            print(f"❌ Error downloading image: {str(e)}")
            self.logger.error(f"Error downloading image {image_url}: {str(e)}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error while downloading image: {str(e)}")
            self.logger.error(
                f"Unexpected error downloading image {image_url}: {str(e)}"
            )
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
        print("🔍 Looking for related images...")
        image_extensions = [".jpg", ".jpeg", ".png"]
        model_number = model_id.split(".")[0]
        moved_count = 0

        # Get list of files to move before starting moves
        files_to_move = []
        for filename in os.listdir(source_dir):
            file_base, ext = os.path.splitext(filename)
            if ext.lower() in image_extensions and file_base.startswith(model_number):
                files_to_move.append(filename)

        # Move files with proper error handling
        for filename in files_to_move:
            source_path = os.path.join(source_dir, filename)
            dest_path = os.path.join(dest_dir, filename)
            try:
                shutil.move(source_path, dest_path)
                moved_count += 1
                self.logger.info(f"Moved related image: {filename} to {dest_dir}")
            except Exception as e:
                print(f"❌ Error moving image {filename}: {str(e)}")
                self.logger.error(f"Error moving related image {filename}: {str(e)}")

        if moved_count > 0:
            print(f"✅ Moved {moved_count} related images")
        else:
            print("ℹ️ No related images found")

    def fix_duplicates(self):
        """Fix duplicate files in the source directory"""
        if not self.source_directory:
            self.safe_print("❌ Source directory not specified")
            return

        self.safe_print("\n🔍 Scanning for duplicate files...")

        # Dictionary to store file groups (with extensions) and their variants
        file_groups = {}

        # First pass: Group files
        for root, _, files in os.walk(self.source_directory):
            for filename in files:
                # Remove numbers in parentheses for comparison but keep the extension
                base_name = re.sub(r"\s*\(\d+\)\s*", "", filename).strip()
                print(f"Base Name {base_name}, File Name {filename}")
                file_path = os.path.join(root, filename)
                if base_name not in file_groups:
                    file_groups[base_name] = []
                file_groups[base_name].append(file_path)

        # Filter only groups with duplicates
        duplicate_groups = {k: v for k, v in file_groups.items() if len(v) > 1}

        if not duplicate_groups:
            self.safe_print("✨ No duplicate files found!")
            return

        total_groups = len(duplicate_groups)
        self.safe_print(f"\n📊 Found {total_groups} files with duplicates")

        processed_count = 0
        for base_name, file_paths in duplicate_groups.items():
            processed_count += 1

            if hasattr(self, "gui"):
                self.gui.update_progress(
                    processed_count, total_groups, f"Processing: {base_name}"
                )

            self.safe_print(f"\n📦 Processing duplicates for: {base_name}")

            # Get file sizes
            file_sizes = [(path, os.path.getsize(path)) for path in file_paths]

            # Sort by size (largest first)
            file_sizes.sort(key=lambda x: x[1], reverse=True)

            # If all files have the same size, keep the one without numbers
            if all(size == file_sizes[0][1] for _, size in file_sizes):
                # Try to find a file without numbers in parentheses
                clean_name_file = next(
                    (
                        path
                        for path in file_paths
                        if not re.search(r"\(\d+\)", os.path.basename(path))
                    ),
                    file_sizes[0][0],  # If none found, use the first file
                )
                files_to_keep = [clean_name_file]
            else:
                # Keep the largest file
                files_to_keep = [file_sizes[0][0]]

            # Move all other files to a subfolder
            for file_path, size in file_sizes:
                if file_path not in files_to_keep:
                    try:
                        subfolder = os.path.join(
                            self.source_directory, "Duplicates", base_name
                        )
                        if not os.path.exists(subfolder):
                            os.makedirs(subfolder)
                        shutil.move(file_path, subfolder)
                        self.safe_print(f"🗑️ Moved: {os.path.basename(file_path)}")
                    except Exception as e:
                        self.safe_print(
                            f"❌ Error Moving {os.path.basename(file_path)}: {str(e)}"
                        )

            # Rename the kept file if it has numbers in parentheses
            kept_file = files_to_keep[0]
            kept_filename = os.path.basename(kept_file)
            if re.search(r"\(\d+\)", kept_filename):
                new_filename = re.sub(
                    r"\s*\(\d+\)\s*$", "", kept_filename
                )  # Remove numbers in parentheses
                new_path = os.path.join(os.path.dirname(kept_file), new_filename)
                try:
                    os.rename(kept_file, new_path)
                    self.safe_print(f"✅ Renamed to: {new_filename}")
                except Exception as e:
                    self.safe_print(f"❌ Error renaming {kept_filename}: {str(e)}")

        self.safe_print("\n✨ Duplicate fixing complete!")


def main():
    root = tk.Tk()
    app = SkyFileOrganizerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
