# HEIC Manager

### What is it?
Manages HEIC media files on Windows - shows them and lets you transfer them over to your iPhone.

![Library grouped by month](docs/screenshots/library.png)

### Usage

Double-click `run.bat` (or run `./run.sh`). The manager opens in your browser at http://127.0.0.1:8765.

- **Choose folder…** lists the HEIC files in a folder, optionally including subfolders.
- **Sort** by date taken, file date, name, size, latitude, longitude or camera. **Group** by year, month, day, location (about 1 km or 10 km) or camera, or by whether a photo has GPS.
- **Click** a photo to select it, **shift-click** to select a range, and **double-click** to see all its metadata.
- **Send to iPhone** shows a QR code. Open it in Safari on the iPhone (same Wi-Fi), accept the self-signed certificate warning, and tap **Save to Photos → Save Images**.
  The original files are sent unchanged, so Photos places each one by its EXIF date and location.
  Photos with no "date taken" are flagged, because Photos would put them on the day they are imported.

The first time it runs, Windows Firewall may ask to allow Python on private networks. Allow it, or the iPhone can't connect.

### Screenshots

<table>
  <tr>
    <td><img src="docs/screenshots/library-dark.png" alt="Library in dark mode"><br><sub>Dark mode</sub></td>
    <td><img src="docs/screenshots/places.png" alt="Grouped by place"><br><sub>Grouped by place, with map links</sub></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/info.png" alt="Photo info sheet"><br><sub>Double-click a photo for its metadata</sub></td>
    <td><img src="docs/screenshots/send.png" alt="Send to iPhone sheet"><br><sub>Send to iPhone: scan the QR code</sub></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="docs/screenshots/iphone.png" alt="Save to Photos page on iPhone" width="300"><br><sub>The page that opens on the iPhone</sub></td>
  </tr>
</table>

<sub>The screenshots use generated sample photos.</sub>
