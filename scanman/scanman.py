 #!/usr/bin/env python3
import os
from os import path
import shutil
import sys
import time
import hashlib
import logging
import subprocess
import ocrmypdf
from glob import glob
from subprocess import Popen


from logpipe import LogPipe


# environment vars
watch_path_env = "INTAKE_DIR"
completed_path_env = "COMPLETED_DIR"


def consume_lines(pipe, consume):
    with pipe:
        for line in iter(pipe.readline, b''): #NOTE: workaround read-ahead bug
            consume(line)

class Scanman:
    def __init__( self, watch_path = None, completed_path = None, sleep_time = 20, delete_files = True):
        self.watch_path = watch_path
        self.completed_path = completed_path
        self.manifest_filename = "file_manifest"
        self.sleep_time = sleep_time or 30
        self.delete_files = delete_files


        logging.debug( "Scanman initialized (" +
                        "watch_path: '" + self.watch_path +
                        "', completed_path: '" + self.completed_path +
                        "', sleep_time: '" + str(self.sleep_time) +
                        "', delete_files: '" + str(self.delete_files) +"')" )

    def get_scan_name( self, scan_path ):
        return os.path.basename( scan_path )

    def get_combined_pdf_filename( self, scan_path ):
        scan_name = self.get_scan_name( scan_path )
        return "%s.combined.pdf" % scan_name

    def get_combined_pdf_path( self, scan_path ):
        scan_name = self.get_scan_name( scan_path )
        return "%s.combined.pdf" % os.path.join(scan_path, scan_name)

    def get_output_pdf_path( self, scan_path ):
        scan_name = self.get_scan_name( scan_path )
        return "%s.pdf" % os.path.join(self.completed_path, scan_name)

    def process_scan( self, scan_path ):

        logging.info( "Processing scan in '%s'" % scan_path )
        valid = self.validate_scan_files( scan_path )
        if not valid:
            logging.error( "Skipping '%s', files could not be verified." % scan_path )
            return

        logging.info( "Creating PDF in '%s'" % scan_path )

        files = self._get_files_from_manifest( scan_path )
        scan_name = self.get_scan_name( scan_path )
        out_path = self.get_output_pdf_path( scan_path )
        combined_path = self.get_combined_pdf_path( scan_path )
        combined_filename = self.get_combined_pdf_filename( scan_path )

        logging.debug( "scan_name: '%s'" % scan_name )
        logging.debug( "out_path: '%s'" % out_path )
        logging.debug( "no_ocr_path: '%s'" % combined_path )

        ## Step 1: Create a combined PDF
        logging.info( "Creating combined pdf: %s" % combined_path )
        try:
            self.create_combined_pdf( scan_path, files, combined_filename )
        except:
            logging.error( "Error creating combined pdf" )
            raise

        ## Step 2: Create a searchable PDF
        logging.info( "Creating searchable pdf: %s" % out_path )
        try:
            self.create_searchable_pdf( combined_path, out_path )
        except:
            logging.error( "Error creating combined pdf" )
            raise

        if self.delete_files:
            logging.info( "Cleaning out '%s'" % scan_path )
            shutil.rmtree( scan_path )

        logging.info( "Processing completed for %s" % out_path )
        return True



    def validate_scan_files( self, scan_path ):
        logging.info( "Validating '%s'" % scan_path )
        validated = False

        manifest_path = path.join( scan_path, self.manifest_filename )
        cmd = ["shasum",'-a','1','-c', self.manifest_filename]
        logging.debug( "Validating '%s'." % manifest_path )
        logging.debug( "Validation command: '%s'." % " ".join( cmd ) )

        try:
            logpipe = LogPipe(logging.DEBUG)
            with subprocess.Popen(cmd, stdout=logpipe, stderr=logpipe, cwd=scan_path) as s:
                s.communicate()
                logpipe.close()
        except FileNotFoundError as e:
            logging.error( e )
            logpipe.close()
            return False


        if s.returncode != 0:
            logging.error( "Validation return non-zero result (%d), files do not match manifest." % s.returncode )
        else:
            validated = True

        return validated


    def create_combined_pdf( self, scan_path, files, out_path ):

        cmd = ["img2pdf", "-v", "-o", out_path] + sorted(files)
        logging.debug( " ".join( cmd ) )
        try:
            logpipe = LogPipe(logging.DEBUG)
            with subprocess.Popen(cmd, stdout=logpipe, stderr=logpipe, cwd=scan_path) as s:
                s.communicate()
                logpipe.close()

        except FileNotFoundError as e:
            logging.error( e )
            logpipe.close()
            return False

        if s.returncode != 0:
            logging.error( "img2pdf return non-zero result (%d)" % s.returncode )
            return False
        else:
            validated = True



    def create_searchable_pdf( self, input_pdf, output_pdf  ):

        logging.debug( "Working directory: %s" % os.getcwd() )
        try:
            ocrmypdf.ocr( input_pdf,
                          output_pdf,
                          rotate_pages=True,
                          rotate_pages_threshold=13,
                          deskew=True,
                          clean=True )

        except Exception as e:
            logging.error( e )
            return


    def run( self ):
        try:
            while True:

                # Look for all subdirectories that contain a manifest
                glob_pattern = path.join( self.watch_path, "*", self.manifest_filename )
                matches = glob( glob_pattern )

                # Sequentially process results
                for match in matches:
                    try:
                        scan_path = path.dirname( match )
                        self.process_scan( scan_path )
                    except Exception as e:
                        logging.error( e )
                        logging.exception( "Exception" )

                time.sleep( self.sleep_time )
        except KeyboardInterrupt:
            logging.info( "SIGINT received: stopping" )
            exit

    def _get_files_from_manifest( self, scan_path ):
        manifest_path = path.join( scan_path, self.manifest_filename )

        logging.debug( "Attempting to read from '%s'" % manifest_path )

        files = []

        with open( manifest_path, "r" ) as f:
            lines = f.readlines()
            for line in lines:
                (hash,file) = line.split()
                files.append( file )

        return files


def configure_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout)

if __name__ == "__main__":
    configure_logger()

    watch_path = os.environ.get(watch_path_env)
    if watch_path is None:
        raise EvironmentError( "%s is not set." % watch_path_env )

    completed_path = os.environ.get(completed_path_env)
    if completed_path is None:
        raise EvironmentError( "%s is not set." % completed_path_env )

    s = Scanman( watch_path=watch_path, completed_path=completed_path, delete_files=True)
    s.run()