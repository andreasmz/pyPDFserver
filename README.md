# pyPDFserver

pyPDFserver provides a bridge FTP server accepting PDFs (for example from your network printer) and applies OCR, image optimization and/or merging to a duplex scan.
The final PDF is uploaded to your target machine (e.g. you NAS) via FTP.

### Installation

pyPDFserver is designed to run in a Docker container, but you can also host it manually. First, install Python (>= 3.10) and install pyPDFserver via pip

```bash
pip install pyPDFserver
```

Then you need to install the external dependencies for ocrmypdf (e.g. tesseract, ghostscript) by following this manual: [https://ocrmypdf.readthedocs.io/en/latest/installation.html](https://ocrmypdf.readthedocs.io/en/latest/installation.html). You can then run pyPDFserver with

```bash
python -m pyPDFserver
```

After first run, two configruation files will be created in your systems configruation folder (refer to the console output to extract the exact paths) named `pyPDFserver.ini` and `profiles.ini`. You need to modify them with your settings and restart pyPDFserver.

### Usage

Now simply connect to your FTP server and upload files. After some time (OCR may take several minutes), they will be uploaded to your server.

#### OCR

pyPDFserver uses OCRmyPDF to apply OCR to your PDF. Simply set `ocr_enabled` to True in your profile to apply OCR to your files. Please note that you should define an language in the profile.ini to get the best OCR results.

#### Duplex scan

pyPDFserver allows you to automatically merge two scans of the front and back pages (i.e. duplex 1 and duplex 2) into a single file. This is intended to be used with an Automatic Document Feeder (ADF). Keep the following in mind:
- The uploaded files must match the `input_duplex1_name` and `input_duplex1_name` templates in your profile.ini
- The back pages must have reversed order in the pdf file (as you simply turn them around for scanning)
- The page count of both files must match or the task is rejected

#### Commands 

At any time you can see your progress in the console by using

- **tasks list**: List all running and recently finished or failed tasks

Other useful commands are

- **exit**:  Terminate the server and clear temporary files
- **version**: List the installed version

Some internal commands you don't usually need to use:

- **tasks force_clear**: Clear all scheduled and finished tasks (does not abort the current task)
- **artifacts list**: Internal command to list all artifacts
- **artifacts clean**: Remove some untracked artifacts to release some storage (usually not needed)

### Configruation

##### pyPDFserver.ini

```ini
[SETTINGS]
# Set here the desired log level (CRITICAL, ERROR, WARNING, INFO, DEBUG)
log_level = INFO
# If set to False, disable interactive console input
use_prompt_session = False
# If set to true, use colors for the console output
log_colors = True
# If set to true, create log files
log_to_file = True
# Time for the backpages of a duplex scan to arrive after the front page upload before
# timing out. Set to zero to disable the timeout
duplex_timeout = 600
# If set to True, pyPDFserver will search after start for old temporary files and delete them
clean_old_temporary_files = True

[FTP]
host = 
local_ip = 127.0.0.1
port = 21
# Define passive ports as a comma seperated list, e.g. 6000,6001,6010-6020,6030
# If running behind a NAT (e.g. in a Docker container), you should define some ports here
# and allow them in the network setings of your firewall
passive_ports = 23001-23010

[EXPORT_FTP_SERVER]
# Set here the address and credentials for the external FTP server
host = 
port = 
username = 
password = 
# If your pyPDFserver is running behind a NAT (e.g. in a Docker container), you may want
# to set control ports (the port used to open a connection to the external FTP server)
# and allow them in the network settings of your firewall
control_port = 23000
```


##### profiles.ini

```ini
# You can define different profiles to use different settings (e.g. different languages for OCR,
# different optimization levels or file names). Every profile must have a unique username.
# All other fields fallback to the DEFAULT profile if not provided. 


[DEFAULT]
# The username for the FTP server
username = pyPDFserver
# The password for the FTP server. Note that after first run it will be replaced with
# a hash value. To change it, remove its value and set it your password. After next run,
# it will be again replace with it hash value
password = 

# OCR settings
# Refer to https://ocrmypdf.readthedocs.io/en/latest/optimizer.html for a more thorough explanation

ocr_enabled = False
# Set the three letter country code for tesseract OCR. You must first install the language 
# pack for tesseract
ocr_language = 
# Correct pages that were scanned at a skewed angle by rotating them back into place
# (--deskew option for OCRmyPDF)
ocr_deskew = True
# Optimization level passed to OCRmyPDF
# (e.g. 0: No optimization, 1: lossless optimiations, 2: some lossy optimizations, 3: aggressive optimization)
ocr_optimize = 1
# Attempts to determine the correct orientation for each page and rotates the page if necessary
# (--rotate-pages paramter for OCRmyPDF)
ocr_rotate_pages = True
# (--tesseract-timeout paramter for OCRmyPDF)
ocr_tesseract_timeout = 60

# File name settings
# When uploading a file to pyPDFserver, it is matched against the given template strings
# and rejected if not matching any. You can use tags (which are replaced by pyPDFserver with
# regex commands) to catch groups
# Availabe tags:
#   (lang): Catch 3 Letter language code
#   (*): Catch everything
# In the export_duple_name you can also use
#   (*1): Fill in (*) from duplex1
#   (*2): Fill in (*) from duplex2

# If set to true, all file names 
input_case_sensitive = True
# Template string for pdf files
input_pdf_name = SCAN_(*).pdf
# Template string to export pdf files
export_pdf_name = Scan_(*).pdf
# Template string for duplex pdf files (1 for front pages, 2 for back pages)
input_duplex1_name = DUPLEX1_(*).pdf
input_duplex2_name = DUPLEX2_(*).pdf
# Template string to export duplex pdf files
export_duplex_name = Scan_(*1)_(lang).pdf
# Path on the external FTP server to upload to
export_path = 

# Two example profiles. You can define as many as you like
[DE]
username = pyPDFserver_de
ocr_enabled = True
ocr_language = deu

[EN]
username = pyPDFserver_en
ocr_enabled = True
ocr_language = eng
```

