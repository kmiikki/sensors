# csv2utf8 Utility

## Introduction

When handling text data on a Raspberry Pi or other Linux systems, you should ensure that your system’s locale is set to UTF-8 before logging or processing data. UTF-8 is a more modern and versatile character encoding than ISO-8859-1 (Latin-1). Many Python scripts (including some in this repository) require that data files are in UTF-8 format.

### Setting Locale to UTF-8 on Raspberry Pi OS (Bookworm)

1. Open **Preferences** → **Raspberry Pi Configuration**.
2. Go to the **Localisation** tab and click **Set Locale…**.
3. Choose, for example:
   - **Language**: en (English)
   - **Country**: United States
   - **Character Set**: UTF-8
4. Click **OK** to apply the changes and reboot if prompted.

### Converting ISO-8859-1 Files to UTF-8

If the data you have is stored in ISO-8859-1, you can convert it to UTF-8 by using the included `csv2utf8.py` utility. 

Before running conversions, you can confirm a file’s encoding by running:
```
file -is filename
```
If the output shows `charset=iso-8859-1`, then it needs converting. Some of the other data handling scripts in this repository specifically require that data files are in UTF-8 format, so converting them first can save time and prevent errors.

## Usage Instructions

1. **Clone or download** this repository to your local machine or Raspberry Pi.

2. **Navigate** to the directory containing `csv2utf8.py`.

3. **Check the file’s execution permissions** (optional):
   ```
   chmod +x csv2utf8.py
   ```
   You can then either run it directly (`./csv2utf8.py`) or use `python3 csv2utf8.py`.

4. **Run the script**:
   ```
   python3 csv2utf8.py
   ```
   - The script looks for all `.txt` and `.csv` files in the current directory.
   - It uses the `file` command to check if a file is encoded in `iso-8859-1`.
   - If an `iso-8859-1` file is found, the script reads it and creates a **utf-8** subdirectory (if it does not already exist).
   - The file is then written into the **utf-8** directory, re-encoded in UTF-8.

5. **Confirm conversion**:  
   Inside the **utf-8** directory, you will find new copies of any converted files. To verify they are now in UTF-8, you can run `file -is filename` again on the converted files.

That’s it! You can now use these converted files (stored in the **utf-8** folder) with any script or application that expects UTF-8 data.

