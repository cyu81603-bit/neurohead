"""Bounded JSONL diagnostics and replaceable latest status for long-running control."""
import json,logging,os
from logging.handlers import RotatingFileHandler
from pathlib import Path
class JsonlLog:
    def __init__(self,path,max_bytes=8*1024*1024,backups=2):
        self.handler=RotatingFileHandler(path,maxBytes=max_bytes,backupCount=backups,encoding="utf-8",delay=False)
        self.handler.setFormatter(logging.Formatter("%(message)s"))
    def write_row(self,row):
        message=json.dumps(row,separators=(",",":"))
        self.handler.emit(logging.LogRecord("nh22",logging.INFO,"",0,message,(),None))
    def close(self):self.handler.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
def write_status(path,value):
    path=Path(path);temporary=path.with_suffix(path.suffix+".tmp")
    try:
        temporary.write_text(json.dumps(value),encoding="utf-8")
        os.replace(temporary,path)
    except OSError:
        # UI status is best effort; control input remains subject to freshness checks.
        pass
