# NALANDABODHI TODO / WISH LIST:

* Log activity to file, not just to console. Include file size and elapsed time per download.
* Write a single "table of contents" file to the download folder.
  * There should perhaps be two files: a Python-friendly JSON file, and a CSV export of the file, for easy use with Excel or Google Sheets.

* Add an option to delete Zoom recordings that have already been downloaded
  * Maybe include an "older than" parameter -- either a date or a # of days from today -- so that the most recent Zoom cloud recordings are not deleted.

* Add the ability to upload to S3 locations
  * Rule- or pattern-based renaming of Zoom files to the desired NB S3 naming convention
  * Log successfully uploaded files
  * Delete local copies of successfully uploaded files

* Develop a utility that facilitates matching of Zoom recordings with S3 recordings.
  * The purpose is to identify Zoom recordings that have already been uploaded to S3.
