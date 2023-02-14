from PIL import Image
from functools import cached_property
from jinja2 import Environment
from jinja2 import FileSystemLoader
from pathlib import Path
from pathlib import PurePosixPath
from urllib.request import Request
from urllib.request import urlopen
from urllib.request import urlretrieve
import argparse
import piexif
import time
import sys
import xml.etree.ElementTree


# -- Set up argparse ----------------------------------------------------------


parser = argparse.ArgumentParser(
    description="Downloads daily Bing image and metadata.",
)
parser.add_argument(
    "--download",
    type=Path,
    default=None,
    help=(
        "Only download images, do not generate static site. "
        "Provide path to download directory."
    ),
)
args = parser.parse_args()


# -- Globals ------------------------------------------------------------------


# File paths.
if args.download:
    dir_www = args.download
    dir_img = args.download
    dir_thumbs = args.download
else:
    dir_www = Path("www")
    dir_img = dir_www / "images"
    dir_thumbs = dir_www / "thumbs"
dir_www.mkdir(parents=True, exist_ok=True)
dir_img.mkdir(parents=True, exist_ok=True)
dir_thumbs.mkdir(parents=True, exist_ok=True)
dir_tmpl = Path("templates")


class BingImage:
    def __init__(self, path: Path):
        self.path = path
        self.date = time.strptime(self.path.stem, "%Y%m%d")
        self.display_date = time.strftime("%B %e, %Y", self.date)
        self.display_month = time.strftime("%B %Y", self.date)
        self.thumb_path = dir_thumbs / f"{self.path.stem}.webp"
        self.thumb_url = PurePosixPath(self.thumb_path.relative_to(dir_www))
        self.html_path = (
            dir_www
            / str(self.date.tm_year)
            / f"{self.date.tm_mon:02d}"
            / f"{self.date.tm_mday:02d}.html"
        )
        self.html_month_path = (
            dir_www / str(self.date.tm_year) / f"{self.date.tm_mon:02d}" / "index.html"
        )
        self.url = PurePosixPath(self.path.relative_to(dir_www))
        self.html_url = PurePosixPath(self.html_path.relative_to(dir_www))
        self.html_month_url = PurePosixPath(self.html_month_path.relative_to(dir_www))

    @cached_property
    def Image(self):
        return Image.open(self.path)

    @cached_property
    def exif(self):
        return piexif.load(str(self.path))

    @cached_property
    def title(self):
        return self.exif["0th"][piexif.ImageIFD.ImageDescription].decode("latin1")

    @cached_property
    def copyright(self):
        return self.exif["0th"][piexif.ImageIFD.Copyright].decode("latin1")

    @cached_property
    def filesize(self) -> float:
        """File size in MB."""
        return round(self.path.stat().st_size / 1024 / 1024, 2)

    def write_thumbnail(self) -> None:
        if self.thumb_path.exists():
            return
        i = self.Image
        i.thumbnail((480, 480))
        i.save(self.thumb_path, quality=70)


# -- Download images-----------------------------------------------------------


# # Using json API from bing homepage...
# r = urlopen("https://www.bing.com/hp/api/model")
# bing = json.loads(r.read().decode("utf8"))
# for m in bing["MediaContents"]:

#     # Parse date.
#     date_struct = time.strptime(m["FullDateString"], "%b %d, %Y")
#     date = time.strftime("%Y%m%d", date_struct)

#     # Get image URL and replace size with UHD size parameter.
#     ic = m["ImageContent"]
#     url = "https://www.bing.com" + ic["Image"]["Url"]
#     url = url.replace("1920x1080.jpg", "UHD.jpg")

#     # Get title and copyright.
#     ic_desc = ic["Title"]
#     ic_copy = ic["Copyright"]


# Using XML archive API (which seems more stable)...
r = urlopen("http://www.bing.com/HPImageArchive.aspx?format=xml&idx=0&n=8")
bing = xml.etree.ElementTree.fromstring(r.read().decode("utf8"))
for ic in bing:

    if ic.tag != "image":
        continue

    # Parse date.
    date_struct = time.strptime(ic.find("startdate").text, "%Y%m%d")
    date = time.strftime("%Y%m%d", date_struct)

    # Get image URL and replace size with UHD size parameter.
    url = "https://www.bing.com" + ic.find("url").text
    url = url.replace("1920x1080.jpg", "UHD.jpg")

    # Get title and copyright.
    ic_desc = ic.find("copyright").text.split("©")[0].strip("() ")
    ic_copy = "©" + ic.find("copyright").text.split("©")[1].strip("() ")

    i = BingImage(dir_img / f"{date}.jpg")
    if not i.path.exists():
        # Download image.
        print(f"Downloading '{url}' to {i.path}")
        urlretrieve(url, filename=i.path)
        # Write metadata as EXIF tags.
        exif_dict = {
            "0th": {
                piexif.ImageIFD.ImageDescription: ic_desc,
                piexif.ImageIFD.Copyright: ic_copy,
            }
        }
        i.Image.save(i.path, quality="keep", exif=piexif.dump(exif_dict))

# If only downloading, exit.
if args.download:
    sys.exit(0)


# -- Generate static site -----------------------------------------------------


# Set up jinja.
jenv = Environment(
    loader=FileSystemLoader(searchpath=[dir_tmpl]),
    lstrip_blocks=True,
    trim_blocks=True,
)

# Build the site by batching images into months, then generate pages
# for each month.
curr_date = None
imgs: list[BingImage] = []
prev_month_img: BingImage = None
for p in sorted(dir_img.iterdir()):

    i = BingImage(p)

    # Generate thumbnail.
    i.write_thumbnail()

    # Set current month.
    if not curr_date:
        curr_date = i.date

    # Generate page.
    print(f"Write {i.html_path}")
    out = jenv.get_template("day.html").render(
        {
            "root": "../../../",
            "img": i,
        }
    )
    i.html_path.parent.mkdir(parents=True, exist_ok=True)
    i.html_path.write_text(out, encoding="utf8")

    # If we have reached the end of the month, generate and reset.
    if i.date.tm_year == curr_date.tm_year and i.date.tm_mon == curr_date.tm_mon:
        imgs.append(i)
    else:
        # Build the month page.
        print(f"Write {imgs[-1].html_month_path}")
        out = jenv.get_template("month.html").render(
            {
                "root": "../../../",
                "imgs": imgs,
                "display_date": imgs[-1].display_month,
                "next_img": i,
                "prev_img": prev_month_img,
            }
        )
        imgs[-1].html_month_path.parent.mkdir(parents=True, exist_ok=True)
        imgs[-1].html_month_path.write_text(out, encoding="utf8")
        # Reset.
        curr_date = i.date
        prev_month_img = imgs[-1]
        imgs = []
        imgs.append(i)

# Build the final month page.
print(f"Write {imgs[-1].html_month_path}")
out = jenv.get_template("month.html").render(
    {
        "root": "../../../",
        "imgs": imgs,
        "display_date": imgs[-1].display_month,
        "prev_img": prev_month_img,
    }
)
imgs[-1].html_month_path.parent.mkdir(parents=True, exist_ok=True)
imgs[-1].html_month_path.write_text(out, encoding="utf8")

# Build the home page using the final image and month.
index_path = dir_www / "index.html"
print(f"Write {index_path}")
out = jenv.get_template("home.html").render(
    {
        "root": "",
        "img": imgs[-1],
    }
)
index_path.write_text(out, encoding="utf8")
