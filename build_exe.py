import os
import sys

import PyInstaller.__main__

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Define icon path
icon_path = os.path.join(script_dir, "icon.ico")

# Set the output filename with the .exe extension
output_filename = "3DSky_Organizer_multiple.exe"

PyInstaller.__main__.run(
    [
        "sky_organizer_gui.py",  # your main script
        "--onefile",  # create a single executable
        "--windowed",  # prevent console window from appearing
        f"--add-data={icon_path}:.",  # include the icon
        "--icon",
        icon_path,  # set executable icon
        "--name",
        output_filename,
        "--clean",  # clean PyInstaller cache
        # f"--add-binary={sys.prefix}/lib/python3.12/site-packages/tk:tk",  # include tkinter
        "--hidden-import",
        "requests",
        "--hidden-import",
        "queue",
    ]
)

print(f"Executable created: {os.path.join('dist', output_filename)}")
