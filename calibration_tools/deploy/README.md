# Copy Python Scripts to /opt/tools directory

copy_pys2tools.py ‑ Recursively locate every ``*.py`` file beneath the current
working directory and copy each one into ``/opt/tools`` (or a user‑supplied
alternative).  After the copy, the script ensures that **user, group, and other**
all have read and execute permissions (``ugo+rx``).

Typical usage
-------------
``$ python copy_pys2tools.py           # copy to /opt/tools (default)``\
``$ python copy_pys2tools.py -d ~/bin  # copy to a custom destination``\
``$ python copy_pys2tools.py -f -q     # force overwrite, stay quiet``

Run with *sudo* if your account cannot write to the destination directory.
