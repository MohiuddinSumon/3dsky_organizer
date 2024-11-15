import os
import subprocess
import sys

from setuptools import setup

# Install required packages
subprocess.check_call(
    [sys.executable, "-m", "pip", "install", "pyinstaller", "requests", "tk"]
)

# setup.py
setup(
    name="3dsky-organizer",
    version="1.0",
    description="3DSky File Organizer",
    author="Md Mohiuddin Ahmed Sumon",
    install_requires=[
        "requests>=2.25.1",
        "tk",
    ],
)
