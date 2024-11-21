# 3DSky Organizer

A GUI application for organizing 3DSky files and folders.

## Options

* **File Organizer**: Organizes individual 3DSky files into categorized folders.
* **Folder Merger**: Merges pre-organized 3DSky folders while updating folder summaries.

## Running the Project

To run the project, execute the `sky_organizer_gui.py` file:
```bash
python sky_organizer_gui.py
```
## Building the Executable

To build the executable, run the `build_exe.py` file:
```bash
python build_exe.py
```
This will create a `3DSky_Organizer.exe` file in the current directory.

## Requirements

* Python 3.x
* tkinter
* requests
* json
* logging
* os
* shutil
* sys
* threading
* time
* typing

## Notes

* The project uses the `3dsky.org` API to fetch model details.
* The project uses the `requests` library to download images.
* The project uses the `tkinter` library to create the GUI.
