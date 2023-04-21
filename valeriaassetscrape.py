import re
import os


filestring = ""
with open("ttsassets", encoding="utf8", errors="ignore") as my_file:
    filestring = my_file.read()

pattern = r"https://.*\.(jpg|png)"
match = re.search(pattern, filestring)

with open("asseturls.txt", "w") as dump:
    for url in match:
        dump.write(url)
