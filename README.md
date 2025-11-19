# BlockTron
BlockTron Code Repo to power BlockTron LED dashboard

Designed for Adafruit CircuitPython 9.2.7 on 2025-04-01; Adafruit MatrixPortal S3 with ESP32S3

# VS Code Setup
- Install VS Code
- Install VS Code Extension "CircuitPython" by joedevivo

# General CircuitPython Setup
- Pull down Version 9.x Adafuit CircuitPython libraries from https://circuitpython.org/libraries
- Unpack the bundle zip file
- Create a "lib" folder under the project's "Source" folder
- From the bundle folder, copy all dependent libraries (folder) from the "lib" subfolder into the project's "lib" folder. Note: To find dependnecies, see "import" references at top of each script
- Install the IDE to interact with the device: https://codewith.mu/
- Create the following configuration files and their configurations under ./Source directory:
    - `"settings.toml"` and populate configurations below with the appropriate SSID and password:

  ```toml
  CIRCUITPY_WIFI_SSID = "<Your Local SSID>" 
  CIRCUITPY_WIFI_PASSWORD = "<Your SSID Password>"
  ```

    - `"device_keys.json"` with the specific device configurations (Template below) and their values (See product owner):

  ```json
  {
    "deviceId": "<deviceId>",
    "apiKey": "<apiKey>"
  }
  ```

# Connect The Device
- Plug in the device to your PC. 
- Start up Mu IDE. If prompted to select mode, select "CircuitPython".

# Dev Deployment in VS Code
- Go to command palette and type "Tasks: Run Tasks"
- Select or Type "Deploy to CircuitPython Device"

# Important Identifiers
- microconstroller.nvm has a few flags:
  - Index 0:
    - 0: Normal mode
    - 1: Active Download (set usb to readonly)
    - 2: Pending Verify
    - 3: Swap Pending (boot.py)
  - Index 1:
    - The value here is a ticker for retries in attempting to update before a rollback occurs.
