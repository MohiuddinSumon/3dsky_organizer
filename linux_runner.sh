#!/bin/bash

# make this file executable: chmod +x linux_runner.sh
# allow linux_runner.desktop lunching 


# Change these variables to match your setup
# FOLDER_PATH="/home/user/Desktop/tg-downloader"
FOLDER_PATH="/home/yourpath/3dsky-organizer/"
SCRIPT_NAME="sky_organizer_gui.py"

# Print current working directory for debugging
echo "Current working directory: $(pwd)"

# Check if folder exists
if [ ! -d "$FOLDER_PATH" ]; then
    echo "Error: Folder '$FOLDER_PATH' does not exist"
    read -p "Press Enter to exit..."
    exit 1
fi

# List contents of current directory for debugging
echo "Contents of current directory:"
# ls -la

# Check if .venv directory exists
if [ ! -d "$FOLDER_PATH/.venv" ]; then
    echo "Error: Virtual environment directory '.venv' not found in $FOLDER_PATH"
    echo "Please make sure you have created a virtual environment using:"
    echo "python -m venv .venv"
    read -p "Press Enter to exit..."
    exit 1
fi

# Check if Python script exists
if [ ! -f "$FOLDER_PATH/$SCRIPT_NAME" ]; then
    echo "Error: Python script '$SCRIPT_NAME' not found in $FOLDER_PATH"
    read -p "Press Enter to exit..."
    exit 1
fi

# Change to the specified directory
cd "$FOLDER_PATH"

# Activate virtual environment and run script
source .venv/bin/activate
which python
python "$SCRIPT_NAME"

echo "Script execution completed"
read -p "Press Enter to exit..." 