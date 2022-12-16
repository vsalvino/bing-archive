from PIL import Image
from functools import cached_property
from jinja2 import Environment
from jinja2 import FileSystemLoader
from pathlib import Path
from pathlib import PurePosixPath
from typing import List
from typing import Tuple
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen
from urllib.request import urlretrieve
import argparse
import json
import piexif
import string
import time


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


# -- Utilities ----------------------------------------------------------------


# File paths.
if args.download:
    dir_www = args.download
    dir_img = args.download
    dir_thumbs = args.download
    dir_data = args.download
else:
    dir_www = Path("www")
    dir_img = dir_www / "images"
    dir_thumbs = dir_www / "thumbs"
    dir_data = dir_www / "data"
dir_www.mkdir(parents=True, exist_ok=True)
dir_img.mkdir(parents=True, exist_ok=True)
dir_thumbs.mkdir(parents=True, exist_ok=True)
dir_data.mkdir(parents=True, exist_ok=True)
dir_tmpl = Path("templates")


class BingImage:
    def __init__(self, path: Path):
        self.path = path
        self.date = time.strptime(self.path.stem, "%Y%m%d")
        self.display_date = time.strftime("%B %e, %Y", self.date)
        self.display_month = time.strftime("%B %Y", self.date)
        self.thumb_path = dir_thumbs / f"{self.path.stem}.webp"
        self.thumb_url = PurePosixPath(self.thumb_path.relative_to(dir_www))
        self.data_path = dir_data / f"{self.path.stem}.json"
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
    def data(self) -> dict:
        return json.loads(self.data_path.read_text())

    @property
    def Image(self):
        return Image.open(self.path)

    def write_thumbnail(self):
        if self.thumb_path.exists():
            return
        i = self.Image
        i.thumbnail((480, 480))
        i.save(self.thumb_path, quality=70)

    def write_data(self, data: dict):
        self.data_path.write_text(json.dumps(data), encoding="utf8")


def request_json(url: str) -> Tuple[int, dict]:
    """
    Makes an HTTP request and parses the JSON response.
    """
    req = Request(
        url,
        headers={"Accept": "application/json"},
    )

    # Open the request and read the response.
    code = 0
    text = ""
    try:
        r = urlopen(req)
        code = r.code
        text = r.read().decode("utf8")
    # Non-200 statuses can be read similarly.
    except HTTPError as err:
        code = err.code
        text = err.read().decode("utf8")

    return (code, json.loads(text))


# -- Download images-----------------------------------------------------------


code, bing = request_json("https://www.bing.com/hp/api/model")

for m in bing["MediaContents"]:

    # Parse date.
    date_struct = time.strptime(m["FullDateString"], "%b %d, %Y")
    date = time.strftime("%Y%m%d", date_struct)

    i = BingImage(dir_img / f"{date}.jpg")

    # Get image URL and replace size with UHD size parameter.
    ic = m["ImageContent"]
    url = "https://www.bing.com" + ic["Image"]["Url"]
    url = url.replace("1920x1080.jpg", "UHD.jpg")
    if not i.path.exists():
        # Download image.
        print(f"Download {i.path}")
        urlretrieve(url, filename=i.path)
        # Write metadata as EXIF tags.
        exif_dict = {
            "0th": {
                piexif.ImageIFD.ImageDescription: ic["Title"],
                piexif.ImageIFD.Copyright: ic["Copyright"],
            }
        }
        i.Image.save(i.path, quality="keep", exif=piexif.dump(exif_dict))

    if not args.download and not i.data_path.exists():
        # Write json to file.
        i.write_data(m)

# If only downloading, exit.
if args.download:
    import sys

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
imgs: List[BingImage] = []
prev_month_img: BingImage = None
for p in dir_img.iterdir():

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
                "date": curr_date,
                "display_date": imgs[-1].display_month,
                "next_img": i,
                "prev_img": prev_month_img,
            }
        )
        imgs[-1].html_month_path.parent.mkdir(parents=True, exist_ok=True)
        imgs[-1].html_month_path.write_text(out, encoding="utf8")
        # Reset.
        curr_date = img_date
        prev_month_img = imgs[-1]
        imgs = []
        imgs.append(i)

# Build the final month page.
print(f"Write {imgs[-1].html_month_path}")
out = jenv.get_template("month.html").render(
    {
        "root": "../../../",
        "imgs": imgs,
        "date": curr_date,
        "display_date": time.strftime("%B %Y", curr_date),
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
        "date": curr_date,
        "display_date": time.strftime("%B %Y", curr_date),
    }
)
index_path.write_text(out, encoding="utf8")
