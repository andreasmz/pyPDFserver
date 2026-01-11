# pyPDFserver

![PyPI - Version](https://img.shields.io/pypi/v/pyPDFserver?style=for-the-badge&logo=pypi&link=https%3A%2F%2Fpypi.org%2Fproject%2FpyPDFServer%2F)
![Docker Image Version](https://img.shields.io/docker/v/andreasmz/pypdfserver?style=for-the-badge&logo=Docker&label=Docker&link=https%3A%2F%2Fhub.docker.com%2Fr%2Fandreasmz%2Fpypdfserver)


pyPDFserver provides a bridge FTP server that accepts PDFs (for example, from your network printer) and applies OCR, image optimization, and/or merging to duplex scans.
The final PDF is uploaded to your target machine (e.g., your NAS) via FTP.

### Installation

pyPDFserver is designed to run in a Docker container, but you can also host it manually.

1. Install Python (>= 3.10) and install pyPDFserver via pip:

```bash
pip install pyPDFserver
```

2. Install the external dependencies for OCRmyPDF (e.g., Tesseract, Ghostscript) by following the manual: [https://ocrmypdf.readthedocs.io/en/latest/installation.html](https://ocrmypdf.readthedocs.io/en/latest/installation.html)

3. Run pyPDFserver:

```bash
python -m pyPDFserver
```

After the first run, two configuration files will be created in your system's configuration folder (refer to the console output to see the exact paths) named `pyPDFserver.ini` and `profiles.ini`. You need to modify them with your settings and restart pyPDFserver.

### Docker

A Docker image is available, including some popular languages (English, French, Spanish, German, Italian, Portuguese, Dutch, Polish). It also includes `jbig2dec` and `pngquant` for OCRmyPDF optimization.  

After pulling the image, adjust the following settings in your Docker container:

- Map the settings folder to your machine. Depending on your OS, it may be located at:

| Platform      | Default Config Path (platformdirs.site_config_dir) |
|---------------|----------------------------------------------------|
| Windows       | C:\ProgramData\pyPDFserver                       |
| macOS         | /Library/Application Support/pyPDFserver         |
| Linux         | /etc/xdg/pyPDFserver                              |

- Create the `pyPDFserver.ini` and `profiles.ini` files in the config dir.  
  - You can skip this step and run pyPDFserver first—it will crash due to missing settings but will create the files with default values.
- Map the ports for FTP server (default 21) and web interface (default 80) to your desired ports. You can also change the default internal ports in the `pyPDFserver.ini`.
- Map the ports for the passive FTP server (default 23000–23010) to the same ports. It's important to use the same ports locally and externally.
- Set the entry point to `python -m pyPDFserver`

### Usage

Connect to your FTP server and upload files. OCR processing may take several minutes. Processed files will be uploaded to your external server.  You can view the status of recent jobs via the web interface (default port 80).

#### OCR

pyPDFserver uses OCRmyPDF to apply OCR to your PDFs. Enable OCR in your profile by setting `ocr_enabled = True`. Define the OCR language in `profiles.ini` for best results.

#### Duplex scan

pyPDFserver can automatically merge front and back page scans (duplex 1 and duplex 2) into a single PDF, suitable for Automatic Document Feeders (ADF).  

- Uploaded files must match the `input_duplex1_name` and `input_duplex2_name` templates in your profile.
- Back pages must be reversed (you simply turn them around for scanning).
- Page counts must match or the task will be rejected.

#### Commands 

**User Commands:**

- `exit`: Terminate the server and clear temporary files.
- `version`: Display the installed version.
- `tasks abort`: Abort all scheduled tasks (currently running tasks cannot be aborted).

**Internal Commands (rarely needed):**

- `tasks list`: List all running, finished, or failed tasks.
- `tasks clean`: Clean old tasks and remove temporary files (automatically performed every 5 minutes).
- `tasks clear`: Abort all scheduled tasks and clear finished tasks.
- `artifacts list`: List all artifacts.
- `artifacts clean`: Remove untracked artifacts to release storage.

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
# Set a time limit in minutes to keep old tasks in cache before garbage collecting them
tasks_keep_time = 180
# Define a soft limit of how many threads are used. Leave blank to not use a limit
num_threads = 

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

# OCR settings
# Refer to https://ocrmypdf.readthedocs.io/en/latest/optimizer.html for a more detailed explanation

ocr_enabled = False
# Set the three-letter language code for Tesseract OCR. You can provide multiple languages serperated by a plus
# You must install the corresponding Tesseract language pack first.
ocr_language = 
# Correct pages that were scanned at a skewed angle by rotating them into alignment
# (--deskew option for OCRmyPDF)
ocr_deskew = True
# Optimization level passed to OCRmyPDF
# (e.g. 0: no optimization, 1: lossless optimizations,
#  2: some lossy optimizations, 3: aggressive optimization)
ocr_optimize = 1
# JPEG quality in percent (integer from 0 to 100). Leave blank to use default. Is only used with ocr_optimize >= 1
ocr_jpg_quality =
# PNG quality in percent (integer from 0 to 100). Leave blank to use default. Is only used with ocr_optimize >= 1
ocr_png_quality =
# Color conversion strategy passed to ghostscript by OCRmyPDF. Set for example to 'Gray' to convert to grayscale image. 
# Leave blank to not alter the colorspace.
ocr_color_conversion_strategy =
# Attempt to determine the correct orientation for each page and rotate it if necessary
# (--rotate-pages parameter for OCRmyPDF)
ocr_rotate_pages = True
# Timeout (in seconds) for Tesseract processing per page
# (--tesseract-timeout parameter for OCRmyPDF)
ocr_tesseract_timeout = 60


# Two example profiles. You can define as many profiles as you like
[DE]
username = pyPDFserver_de
ocr_enabled = True
ocr_language = deu

[EN]
username = pyPDFserver_en
ocr_enabled = True
ocr_language = eng

# You can define multiple languages for OCR
[DE_EN]
username = pyPDFserver_de_en
ocr_enabled = True
ocr_language = deu+eng
```

