# Measuring your own printer

Looking at a print and saying "something seems to be missing" is unreliable. The pages made by [`tools/testpages.py`](../tools/testpages.py) turn each question into something you can read off the paper. Use them to check a new roll, a different paper width, another firmware, or a different Paperang model, and put the numbers in a bug report.

```bash
python3 tools/testpages.py boxes boxes.png
paperang-c2 image boxes.png --raw --mode threshold      # --raw: 1 image pixel = 1 printed dot, no margins added
```

Let the paper hang free off the edge of the table while it prints and tear each strip off afterwards. A strip that curls against the desk or the laptop smudges the print and wrecks the evidence. Photograph the strip flat; if you open a phone photo on a Mac, apply the EXIF rotation first (`PIL.ImageOps.exif_transpose`) or you will crop the wrong region.

| Page | Question it answers | How to read it |
|---|---|---|
| `boxes` | Where does the paper really end? | Five outline boxes at different positions and line widths. A box whose right (or left) side is missing was printed partly off the paper. On a 4-inch roll under a 110 mm setting: boxes reaching dot 1230 lost their right side, the one ending at dot 1188 was complete, line width made no difference. So the printable width was about 1200 dots. |
| `edges` | Which dots reach the paper at each end? | Numbers at the first and last dots of the line, with ticks. Read the first and last number you can still see. |
| `stairs` | Is any data dropped? | One bar per 7-row data frame, each longer than the previous, every fifth labelled `#1`, `#6`, … A missing frame is a gap in the staircase; count the labels to see which. This is how the timing bugs were found: closing the link too early cut the top frames, and waiting for each acknowledgement between frames lost others. |
| `ruler` | How much paper is fed before the first row, and is the vertical scale right? | Millimetre ticks with labels. |

## Reporting

Please include: model and firmware (`paperang-c2 info`), the paper width setting and the real roll width (measure it with a ruler), the operating system and Bluetooth adapter of the host, and a photo of the pages above. Anything on another model is valuable, because only one C2 has been tested.
