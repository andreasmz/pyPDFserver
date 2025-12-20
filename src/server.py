from pyftpdlib.handlers import TLS_FTPHandler



class FTPserver(TLS_FTPHandler):

    banner = "pyPDFserver"

    def ftp_STOR(self, file, mode="w"):
        return super().ftp_STOR(file, mode)

    def ftp