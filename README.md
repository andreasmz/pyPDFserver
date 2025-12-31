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

### Docker

A docker image is available including the most popular languages.

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
# Set the desired log level (CRITICAL, ERROR, WARNING, INFO, DEBUG)
log_level = INFO
# If set to False, disable interactive console input
interactive_shell = False
# If set to True, enable colored console output
log_colors = True
# If set to True, create log files
log_to_file = True
# Time (in seconds) to wait for the back pages of a duplex scan after the
# front page upload before timing out. Set to zero to disable the timeout.
duplex_timeout = 600
# If set to True, pyPDFserver will search for old temporary files at startup
# and delete them
clean_old_temporary_files = True

[FTP]
local_ip = 127.0.0.1
port = 21
# If pyPDFserver is running behind a NAT, you may need to set the IP address
# that clients use to connect to the FTP server to prevent foreign address errors.
public_ip = 
# In FTP passive mode, clients open both control and data connections to bypass
# NATs on the client side. If pyPDFserver itself is running behind a NAT, you
# need to open the passive ports. By default, FTP servers use random ports, but
# you can define a custom list or range of ports.
# Write them as a comma-separated list (e.g. 6000,6010-6020,6030).
passive_ports = 23001-23010

[EXPORT_FTP_SERVER]
# Set the address and credentials for the external FTP server
host = 
port = 
username = 
password = 
# If pyPDFserver is running behind a NAT (e.g. in a Docker container), you may
# want to define control ports (the ports used to open connections to the
# external FTP server) and allow them in your firewall settings.
control_port = 23000

[WEBINTERFACE]
# If set to True, start a simple web interface to display currently scheduled,
# running, and finished tasks
enabled = True
# Set the port for the web server. If empty, it defaults to 80 or 443 (TLS enabled).
port = 
```


##### profiles.ini

```ini
# You can define multiple profiles to use different settings (e.g. different OCR languages,
# optimization levels, or file name templates). Each profile must have a unique username.
# Any fields not explicitly set will fall back to the DEFAULT profile.


[DEFAULT]
# Username for the FTP server
username = pyPDFserver
# Password for the FTP server. Note that after the first run it will be replaced with
# a hash value. To change the password later, remove its value and set a new password.
# After the next run, it will again be replaced with its hash value.
password = 

# OCR settings
# Refer to https://ocrmypdf.readthedocs.io/en/latest/optimizer.html for a more detailed explanation

ocr_enabled = False
# Set the three-letter language code for Tesseract OCR.
# You must install the corresponding Tesseract language pack first.
ocr_language = 
# Correct pages that were scanned at a skewed angle by rotating them into alignment
# (--deskew option for OCRmyPDF)
ocr_deskew = True
# Optimization level passed to OCRmyPDF
# (e.g. 0: no optimization, 1: lossless optimizations,
#  2: some lossy optimizations, 3: aggressive optimization)
ocr_optimize = 1
# Attempt to determine the correct orientation for each page and rotate it if necessary
# (--rotate-pages parameter for OCRmyPDF)
ocr_rotate_pages = True
# Timeout (in seconds) for Tesseract processing per page
# (--tesseract-timeout parameter for OCRmyPDF)
ocr_tesseract_timeout = 60

# File name settings
# When uploading a file to pyPDFserver, it is matched against the defined template strings
# and rejected if it does not match any of them. You can use tags (which pyPDFserver replaces
# with regular expression patterns) to capture groups.
# Available tags:
#   (lang): capture a three-letter language code. Multiple languages can be given (seperated by comma)
#   (*): capture any content
# In export_duplex_name you can also use:
#   (*1): insert the (*) match from duplex1
#   (*2): insert the (*) match from duplex2

# If set to True, file name matching is case-sensitive
input_case_sensitive = True
# Template string for incoming PDF files
input_pdf_name = SCAN_(*).pdf
# Template string for exported PDF files
export_pdf_name = Scan_(*).pdf
# Template strings for duplex PDF files (1 = front pages, 2 = back pages)
input_duplex1_name = DUPLEX1_(*).pdf
input_duplex2_name = DUPLEX2_(*).pdf
# Template string for exported duplex PDF files
export_duplex_name = Scan_(*1)_(lang).pdf
# Target path on the external FTP server for uploaded files
export_path = 

# Two example profiles. You can define as many profiles as you like
[DE]
username = pyPDFserver_de
ocr_enabled = True
ocr_language = deu

[EN]
username = pyPDFserver_en
ocr_enabled = True
ocr_language = eng

```

