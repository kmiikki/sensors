#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Sep  4 10:10:42 2024

@author: Kim Miikki
"""
import os
from datetime import datetime

class DataLog:
    """Data log object class"""
    _dt_list = []

    
    # Constructor
    def __init__(self, timestamp: int,
                 file_path = "",
                 name = "",
                 ext = "log",
                 subdirs = True,
                 ts_prefix = False):
        
        self._ts_prefix = ts_prefix
        self._is_header = False
        # Generate logfile name
        self.dt = datetime.fromtimestamp(timestamp)
        self._dt_part = self.dt.strftime("%Y%m%d-%H%M%S")
        if self._dt_part in DataLog._dt_list:
            raise ValueError(f"The given datetime ({self.dt_part}) is already in use. Unable to create a new log object.")
        DataLog._dt_list.append(self._dt_part)
        
        # Is the directory path valid
        if file_path != "":
            if file_path[-1] != "/":
                file_path += "/"
        if subdirs:
            file_path += self._dt_part
            file_path += "/"
        if (len(file_path) > 0) and (not os.path.exists(file_path)):
                os.makedirs(file_path)
        
        # Create a log file
        self.log_name = ""
        self._dir_path = ""
        if ts_prefix:
            self.log_name += self._dt_part
            self.log_name += "-"
        self.log_name += name
        self.log_name += "." + ext
        self.full_path = os.path.abspath(file_path + self.log_name)
        self._dir_path = os.path.abspath(file_path)
        if self._dir_path[-1] != "/":
            self._dir_path += "/"
        open(self.full_path,'w').close()

    
    def write(self, data): # header: list, row: string
        if not self._is_header:
            data = ", ".join(data)
            self._is_header = True
        data += "\n"
        with open(self.full_path, 'a') as f:
            f.write(data)            

    
    @property
    def dir_path(self) ->str:
        return self._dir_path
    
    
    @property    
    def dt_part(self) ->str:
        return self._dt_part

    
    @property    
    def ts_prefix(self) ->bool:
        return self._ts_prefix


    # Destructor
    def __del__(self):
        if self._dt_part in DataLog._dt_list:
            DataLog._dt_list.remove(self._dt_part)
        
class ErrorLog:
    """Error log object class"""
    _log_list = []
    
    # Constructor
    def __init__(self, dir_path = "",
                 name = "error",
                 ext = "log",
                 dt_part = "",
                 ts_prefix = False):

        # Generate full path for the error log
        self._dir_path = dir_path
        if self._dir_path[-1] != '/':
            self._dir_path += "/"
        if ts_prefix and len(dt_part) > 0:
            self._dir_path += dt_part
            self._dir_path += '-'
        self._dir_path += name + "." + ext
        
        # Check if error log object already exists
        if self._dir_path in ErrorLog._log_list:
            raise ValueError(f"The error log object ({self._dir_path}) already exists. Unable to create a new error log object.")
        
        # Create an error log file
        try:
            open(self._dir_path,'w').close()
        except:
            print("Unable to create an error log")
            return
        ErrorLog._log_list.append(self._dir_path)
        self._is_header = False

    
    def write(self, timestamp: int, measurement: int, error_text: str):
        # Convert timestamp to a datetime string
        self.dt = datetime.fromtimestamp(timestamp)
        self.dt_text = self.dt.strftime("%Y-%m-%d %H:%M:%S.%f")
        out = ", ".join([self.dt_text, str(measurement), error_text]) + "\n"
        
        # Frite event to file
        with open(self._dir_path, 'a') as f:
            if not self._is_header:
                f.write("Datetime, Measurement, Event\n")
                self._is_header = True
            f.write(out)


    # Destructor
    def __del__(self):
        if self._dir_path in ErrorLog._log_list:
            ErrorLog._log_list.remove(self._dir_path)


if __name__ == "__main__":
    ...