#!/usr/bin/python3

# Imports
import serial
import argparse
import time
import os
from serial.tools.list_ports import comports
import sys
if sys.version_info >= (3, 11):  # pragma: Python version >=3.11
    import tomllib
else:  # pragma: Python version <3.11
    import tomli as tomllib

class BootloaderFlashUtil:
	def __init__(self, args=[]):
		self.__scriptDir = os.path.dirname(os.path.abspath(__file__))
		self.__rootDir = os.path.abspath(os.path.join(self.__scriptDir, '..', '..', '..'))
		self.__imagesDir = os.path.abspath(os.path.join(self.__rootDir, 'target', 'images'))

		self.__setupArgumentParser(args)
		self.__getFlashAddress()
		self.__setupSerialPort()

	# Setup CLI parser
	def __setupArgumentParser(self, args=[]):
		# Create parser
		self.__parser = argparse.ArgumentParser(description='Util to flash bootloader on RZ Board.\n', epilog='Example:\n\t./bootloader_flash.py')

		# Add arguments
		# Board name
		self.__parser.add_argument('--board_name',
									default='rzg2l-sbc',
									dest='boardName',
									action='store',
									type=str,
									help='Board name to flash bootloader (defaults to: rzg2l-sbc).')
		self.__parser.add_argument('--flash_method',
									default='qspi',
									dest='flashMethod',
									action='store',
									type=str,
									choices=['emmc', 'qspi', 'esd'],
									help='Flash method to use (defaults to: qspi).')

		# Serial port arguments
		self.__parser.add_argument('--serial_port',
									default=None,
									dest='serialPort',
									action='store',
									help='Serial port used to talk to board (defaults to: most recently connected port).')
		self.__parser.add_argument('--serial_port_baud',
									default=115200,
									dest='baudRate',
									action='store',
									type=int,
									help='Baud rate for serial port (defaults to: 115200).')

		# Images
		self.__parser.add_argument('--image_writer',
									default=f'{self.__imagesDir}/Flash_Writer_SCIF_rzg2l-sbc.mot',
									dest='flashWriterImage',
									action='store',
									type=str,
									help="Path to Flash Writer image (defaults to: <path/to/your/package>/target/images/Flash_Writer_SCIF_rzg2l-sbc.mot).")
		self.__parser.add_argument('--image_bl2',
									default=f'{self.__imagesDir}/bl2_bp_rzg2l-sbc.srec',
									dest='bl2Image',
									action='store',
									type=str,
									help='Path to bl2 image (defaults to: <path/to/your/package>/target/images/bl2_bp_rzg2l-sbc.srec).')
		self.__parser.add_argument('--image_fip',
									default=f'{self.__imagesDir}/fip-rzg2l-sbc.srec',
									dest='fipImage',
									action='store',
									type=str,
									help='Path to FIP image (defaults to: <path/to/your/package>/target/images/fip-rzg2l-sbc.srec).')
		self.__parser.add_argument('--image_bid',
									default=f'{self.__imagesDir}/rzg2l-sbc-platform-settings.bin',
									dest='bidImage',
									action='store',
									type=str,
									help='Path to board identification image (defaults to: <path/to/your/package>/target/images/rzg2l-sbc-platform-settings.bin).')

		if args:
			self.__args = self.__parser.parse_args(args)
		else:
			self.__args = self.__parser.parse_args()

	# Setup Serial Port
	def __setupSerialPort(self):
		try:
			if (self.__args.serialPort is None):
				ports = [port.device for port in comports()]
				print(f"Available serial ports: {ports}")
				print(f"Using serial port: {ports[0]}")
				self.__serialPort = serial.Serial(port= ports[0], baudrate = self.__args.baudRate, timeout=60)
			else:
				self.__serialPort = serial.Serial(port=self.__args.serialPort, baudrate = self.__args.baudRate, timeout=60)

		except:
			die(msg='Unable to open serial port.')

	def __getFlashAddress(self):
		configFile = os.path.join(self.__scriptDir, ".." , "config", 'boards_flash_config.toml')
		with open(configFile, "rb") as f:
			flash_info = tomllib.load(f)

		self.__flashAddress = flash_info[self.__args.boardName]

		if self.__flashAddress is None:
			print(f"Board name {self.__args.boardName} is not supported.")
			exit()

	# Setup Serial Port SUP
	def __setupSerialPort_SUP(self):
		try:
			self.__serialPort.baudrate = 921600
		except:
			die(msg='Unable to open serial port 921600 bps.')

	def __wait_for_prompt(self, timeout=30):
		end_time = time.time() + timeout
		buffer = b""
		sent_y = False

		while time.time() < end_time:
			if self.__serialPort.in_waiting:
				buffer += self.__serialPort.read(self.__serialPort.in_waiting)
				decoded = buffer.decode(errors='ignore')

				if not sent_y and "Clear OK" in decoded:
					self.__writeSerialCmd('y')
					sent_y = True  # prevent sending again

				if ">" in decoded:
					break

			time.sleep(0.1)

		print(f'{buffer.decode(errors="ignore")}')

	# Function to write bootloader
	def writeBootloader(self):
		start_time = time.time()

		# Check file exists
		if not os.path.exists(self.__args.flashWriterImage):
			print(f"The file {self.__args.flashWriterImage} does not exist.")
			exit()
		if not os.path.exists(self.__args.bl2Image):
			print(f"The file {self.__args.bl2Image} does not exist.")
			exit()
		if not os.path.exists(self.__args.fipImage):
			print(f"The file {self.__args.fipImage} does not exist.")
			exit()
		if not os.path.exists(self.__args.bidImage):
			print(f"The file {self.__args.bidImage} does not exist.")
			exit()

		# Wait for device to be ready to receive image.
		print("Please power on board. Make sure you changed switches to SCIF download mode.")
		if (self.__args.boardName == "rzv2h-evk"):
			self.__serialRead('Load Program to SRAM')
		else:
			self.__serialRead('please send !')

		# Write flash writer application
		time1 = time.time()
		print("Writing Flash Writer application...")
		self.__writeFileToSerial(self.__args.flashWriterImage)
		self.__serialRead('>')

		time2 = time.time()
		elapsed_time = time2 - time1
		print(f"Elapsed time: Flash Writer: {elapsed_time:.6f} seconds")

		self.__writeSerialCmd('')
		self.__serialRead('>')

		# emmc flash
		if (self.__args.flashMethod == "emmc"):
			self.__handle_emmc_flash(self.__flashAddress["emmc"])
		# qspi flash
		elif (self.__args.flashMethod == "qspi"):
			self.__handle_qspi_flash(self.__flashAddress["qspi"])

		print("Closed serial port.")
		self.__serialPort.close()

		end_time = time.time()
		elapsed_time = end_time - start_time
		print(f"Elapsed time: {elapsed_time:.6f} seconds")

	def __handle_emmc_flash(self, flashAddress):
		self.__writeSerialCmd('EM_E')
		self.__serialRead('Select area')
		self.__writeSerialCmd('1')
		self.__serialRead('>')

		# Changing speed to 921600 bps.
		self.__writeSerialCmd('SUP')
		self.__serialRead('the terminal.')

		self.__setupSerialPort_SUP()
		time.sleep(1)
		self.__writeSerialCmd('')
		self.__serialRead('>')

		# Write BL2
		BL2FlashAddress = flashAddress["BL2"]
		self.__writeSerialCmd('EM_W')
		self.__serialRead('Select area')
		self.__writeSerialCmd(BL2FlashAddress[0])

		self.__serialRead('Please Input Start Address in sector')
		self.__writeSerialCmd(BL2FlashAddress[1])

		self.__serialRead('Please Input Program Start Address')
		self.__writeSerialCmd(BL2FlashAddress[2])
		self.__serialRead('please send !')

		print("Writing BL2...")
		self.__writeFileToSerial(self.__args.bl2Image)
		self.__serialRead('>')

		# Write FIP
		FIPFlashAddress = flashAddress["FIP"]
		self.__writeSerialCmd('EM_W')
		self.__serialRead('Select area')
		self.__writeSerialCmd(FIPFlashAddress[0])

		self.__serialRead('Please Input Start Address in sector')
		self.__writeSerialCmd(FIPFlashAddress[1])

		self.__serialRead('Please Input Program Start Address')
		self.__writeSerialCmd(FIPFlashAddress[2])
		self.__serialRead('please send !')
		print("Writing fip ...")
		self.__writeFileToSerial(self.__args.fipImage)

		self.__serialRead('EM_W Complete!')

		# Write EXT_CSD
		self.__writeSerialCmd('EM_SECSD')
		self.__serialRead('Please Input EXT_CSD Index')
		self.__writeSerialCmd('B1')
		self.__serialRead('Please Input Value')
		self.__writeSerialCmd(FIPFlashAddress[3])
		self.__serialRead('>')

		self.__writeSerialCmd('EM_SECSD')
		self.__serialRead('Please Input EXT_CSD Index')
		self.__writeSerialCmd('B3')
		self.__serialRead('Please Input Value')
		self.__writeSerialCmd(FIPFlashAddress[4])
		self.__serialRead('>')

		# Write board identification
		BIDFlashAddress = flashAddress["BID"]
		self.__writeSerialCmd('EM_WB')
		self.__writeSerialCmd('EM_W')
		self.__serialRead('Select area')
		self.__writeSerialCmd(BIDFlashAddress[0])

		self.__serialRead('Please Input Start Address in sector')
		self.__writeSerialCmd(BIDFlashAddress[1])

		self.__serialRead('Please Input Program Start Address')
		self.__writeSerialCmd(BIDFlashAddress[2])
		self.__serialRead('please send ! (binary)')

		print("Writing board identification...")
		self.__writeFileToSerial(self.__args.bidImage)
		self.__serialRead('>')

	def __handle_qspi_flash(self, flashAddress):
		if not (self.__args.boardName == "rzv2h-evk"):
			self.__writeSerialCmd('XCS')
			self.__wait_for_prompt(60)

		# Changing speed to 921600 bps.
		self.__writeSerialCmd('SUP')
		self.__serialRead('the terminal.')

		self.__setupSerialPort_SUP()
		time.sleep(1)
		self.__writeSerialCmd('')
		self.__serialRead('>')

		# Write BL2
		BL2FlashAddress = flashAddress["BL2"]
		self.__writeSerialCmd('XLS2')
		self.__serialRead('Please Input : H')
		self.__writeSerialCmd(BL2FlashAddress[0])

		self.__serialRead('Please Input : H')
		self.__writeSerialCmd(BL2FlashAddress[1])
		self.__serialRead('please send !')

		print("Writing BL2...")
		self.__writeFileToSerial(self.__args.bl2Image)
		self.__serialRead('>')

		# Write FIP
		FIPFlashAddress = flashAddress["FIP"]
		self.__writeSerialCmd('XLS2')
		self.__serialRead('Please Input : H')
		self.__writeSerialCmd(FIPFlashAddress[0])

		self.__serialRead('Please Input : H')
		self.__writeSerialCmd(FIPFlashAddress[1])
		self.__serialRead('please send !')

		print("Writing fip ...")
		self.__writeFileToSerial(self.__args.fipImage)
		self.__wait_for_prompt()

		# Write board identification
		BIDFlashAddress = flashAddress["BID"]
		if (self.__args.bidImage.endswith('.srec')):
			self.__writeSerialCmd('XLS2')
		else:
			self.__writeSerialCmd('XLS3')
		self.__serialRead('Please Input : H')
		self.__writeSerialCmd(BIDFlashAddress[0])

		self.__serialRead('Please Input : H')
		self.__writeSerialCmd(BIDFlashAddress[1])
		self.__serialRead('please send !')

		print("Writing board identification...")
		self.__writeFileToSerial(self.__args.bidImage)
		self.__wait_for_prompt()

	def __writeSerialCmd(self, cmd):
		self.__serialPort.write(f'{cmd}\r'.encode())

	# Function to write file over serial
	def __writeFileToSerial(self, file):
		with open(file, 'rb') as f:
			self.__serialPort.write(f.read())
			f.close()

	# Function to wait and print contents of serial buffer
	def __serialRead(self, cond='\n'):
		buf = self.__serialPort.read_until(cond.encode())

		if not buf:
			print(f"Returned value {cond} is not the expectation. Exiting.")
			exit()

		print(f'{buf.decode(errors="ignore")}')

# Util function to die with error
def die(msg='', code=1):
	print(f'Error: {msg}')
	exit(code)

def main():
	bootloaderFlashUtil = BootloaderFlashUtil()

	bootloaderFlashUtil.writeBootloader()

if __name__ == '__main__':
	main()
