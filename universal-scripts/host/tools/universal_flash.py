import sys
import os
import json
from dataclasses import dataclass
from serial.tools.list_ports import comports

# Importing utility applications
sys.path.append(os.path.join(os.path.dirname(__file__), 'firmware_compile'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'bootloader_flasher'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'sd_creator'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'uload_bootloader'))
from firmware_compile import FirmwareBuilder, parse_args
from bootloader_flash import BootloaderFlashUtil
from sd_flash import SdFlashUtil
from uload_bootloader_flash import UloadFlashUtil

@dataclass
class FlashInfo:
    bl2: str
    board_identification: str
    fip: str
    flash_writer: str
    ipl_flash_method: str
    rootfs: str
    rootfs_flash_method: str

class UniversalFlashUtil:
    def __init__(self):
        self.__scriptDir = os.path.dirname(os.path.abspath(__file__))
        self.__rootDir = os.path.abspath(os.path.join(self.__scriptDir, '..', '..'))
        self.__imagesDir = os.path.abspath(os.path.join(self.__rootDir, 'target', 'images'))
        self.json_file = "flash_images.json"
        self.boards_data = {}
        self.selected_port = None
        self.selected_baud_rate = 115200
        self.selected_board_name = None
        self.selected_ip_address = "169.254.187.89"
        self.selected_info = None

    def load_json(self):
        try:
            with open(self.json_file, 'r') as f:
                self.boards_data = json.load(f)
        except FileNotFoundError:
            print(f"File '{self.json_file}' not found.")
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")

    def input_menu(self):
        # Board selection
        if not self.boards_data:
            print("No board data loaded.")
            return

        print("Available boards:")
        for idx, board in enumerate(self.boards_data.keys()):
            print(f"{idx + 1}. {board}")

        board_names = list(self.boards_data.keys())
        selection = int(input("Select board by number: ")) - 1
        if selection < 0 or selection >= len(board_names):
            print("Invalid selection.")
            return
        self.selected_board_name = board_names[selection]
        print(f"Selected board: {self.selected_board_name}\n")

        # Serial port and baud rate selection
        ports = [port.device for port in comports()]
        print("Available serial ports:")
        for i, port in enumerate(ports):
            print(f"{i}: {port}")

        index = int(input(f"Select a port by number (Default {ports[0]}): ") or 0)
        if 0 <= index < len(ports):
            self.selected_port = ports[index]
        else:
            print("Invalid number. Try again.")

        self.selected_baud_rate = int(input(f"Enter baud rate (Default {self.selected_baud_rate}): ") or 115200)
        print(f"Selected port [{self.selected_port}] with baud rate: {self.selected_baud_rate}\n")

    def prepare_binaries(self):
        print("\n=== Building firmware artifacts ===")

        # Map paths from images dir + flash_images.json
        bl2_path = os.path.join(self.__imagesDir, "atf", "bl2-rz-cmn.bin")
        bl31_path = os.path.join(self.__imagesDir, "atf", "bl31-rz-cmn.bin")
        dtb_path = os.path.join(self.__imagesDir, "u-boot", "dtbs", self.boards_data[self.selected_board_name]["uboot_dtb"])
        uboot_nodtb_path = os.path.join(self.__imagesDir, "u-boot", "u-boot-nodtb-rz-cmn.bin")

        # Build the args namespace exactly as firmware-compile expects
        args = parse_args([
            "--board", self.selected_board_name,
            "--method", self.boards_data[self.selected_board_name]["ipl_flash_method"],
            "--bl2", bl2_path,
            "--dtb", dtb_path,
            "--bl31", bl31_path,
            "--u-boot-nodtb", uboot_nodtb_path,
            #"--out-dir", os.path.join(self.__imagesDir, "build_artifacts") # it depends, it can be deployed to target/images or custom dir.
        ])

        builder = FirmwareBuilder(args)
        builder.run_all()

    def info_get(self):
        board_data = self.boards_data[self.selected_board_name]

        self.selected_info = FlashInfo(
            bl2=board_data["bl2"],
            board_identification=board_data["board_identification"],
            fip=board_data["fip"],
            flash_writer=board_data["flash_writer"],
            ipl_flash_method=board_data["ipl_flash_method"],
            rootfs=board_data["rootfs"],
            rootfs_flash_method=board_data["rootfs_flash_method"],
        )

    def print_selected_info(self):
        if not self.selected_info:
            print("No board selected.")
            return

        print(f"\nSelected Board: {self.selected_board_name}")
        print("Board Information:")
        print(f"  BL2: {self.selected_info.bl2}")
        print(f"  Board Identification: {self.selected_info.board_identification}")
        print(f"  Flash Writer: {self.selected_info.flash_writer}")
        print(f"  IPL Flash Method: {self.selected_info.ipl_flash_method}")
        print(f"  Rootfs Flash Method: {self.selected_info.rootfs_flash_method}")
        print(f"  Rootfs: {self.selected_info.rootfs}")

    def yes_no_prompt(self, message: str) -> bool:
        while True:
            answer = input(f"{message} (y/n): ").strip().lower()
            if answer in ['y', 'yes']:
                return True
            elif answer in ['n', 'no']:
                return False
            else:
                print("Please enter 'y' or 'n'.")

    def select_ipl_method(self):
        options = {
            1: "BootloaderFlash",
            2: "UloadFlash"
        }

        print("Write IPL method:")
        for key, value in options.items():
            print(f"{key}. {value}")

        while True:
            try:
                choice = int(input("Select write IPL method by number: "))
                return options[choice]
            except ValueError:
                print("Invalid input. Please enter a number.")

    def run(self):
        self.load_json()
        self.input_menu()
        # Get information for the selected board
        self.info_get()
        # Prepare firmware binaries before flashing
        self.prepare_binaries()

        # Write Rootfs
        if(self.yes_no_prompt("Do you want to write the rootfs?")):
            print("Writing rootfs...")
            if (self.selected_info.rootfs_flash_method == "udp"):
                self.selected_ip_address = input(f"Enter IP address for fastboot udp (default {self.selected_ip_address}): ") or self.selected_ip_address
                ether_port = input("Enter the Ethernet port number (default 1): ") or "1"

            # Prepare arguments for SD Flash
            sdflash_args = [
                '--board_name', f"{self.selected_board_name}",
                '--serial_port', f"{self.selected_port}",
                '--serial_port_baud', f"{self.selected_baud_rate}",
                '--fastboot_type', f"{self.selected_info.rootfs_flash_method}",
                '--ether_port', ether_port,
                '--image_rootfs', f"{self.__imagesDir}/{self.selected_info.rootfs}",
                '--ip_address', f"{self.selected_ip_address}",
            ]
            sdFlashUtil = SdFlashUtil(args=sdflash_args)
            sdFlashUtil.writeRootfs()

        # Write IPL
        if(self.yes_no_prompt("Do you want to write the IPL?")):
            # Check if IPL method is selected
            if (self.select_ipl_method() == "BootloaderFlash"):
                print("Writing IPL by bootloader flash...\n")
                bootloader_args = [
                    '--board_name', f"{self.selected_board_name}",
                    '--flash_method', f"{self.selected_info.ipl_flash_method}",
                    '--serial_port', f"{self.selected_port}",
                    '--serial_port_baud', f"{self.selected_baud_rate}",
                    '--image_writer', f"{self.__imagesDir}/{self.selected_info.flash_writer}",
                    '--image_bl2', f"{self.__imagesDir}/{self.selected_info.bl2}",
                    '--image_fip', f"{self.__imagesDir}/{self.selected_info.fip}",
                    '--image_bid', f"{self.__imagesDir}/{self.selected_info.board_identification}"
                ]
                bootloaderFlashUtil = BootloaderFlashUtil(args=bootloader_args)
                bootloaderFlashUtil.writeBootloader()

            # UloadFlash
            else:
                # Write uload bootloader
                print("Writing IPL by Uload bootloader...\n")
                uload_bootloader_args = [
                    '--board_name', f"{self.selected_board_name}",
                    '--serial_port', f"{self.selected_port}",
                    '--serial_port_baud', f"{self.selected_baud_rate}"
                ]
                uloadFlashUtil = UloadFlashUtil(args=uload_bootloader_args)
                uloadFlashUtil.writeUloadBootloader()

def main():
    universalFlashUtil = UniversalFlashUtil()
    universalFlashUtil.run()

if __name__ == '__main__':
    main()
