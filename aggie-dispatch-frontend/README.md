# Aggie Dispatch Frontend

This is a standalone HTML, CSS, and JavaScript export of the Aggie Dispatch student hub. It does not require Fluxscape or a build step.

## Run locally

1. Open index.html in a modern browser, or serve this folder with any static web server.
2. With Python, run python -m http.server 8000 from this folder and open http://localhost:8000.

## Edit

The page markup, styles, and client-side interactions are in index.html. The bulldog mark is embedded as a PNG data URL, so no separate image asset is needed.

## External assets

The page currently loads Tailwind CSS and the Inter, JetBrains Mono, and Newsreader fonts from public CDNs. Internet access is needed for those assets; the page content and inline interactions remain in the exported HTML.
