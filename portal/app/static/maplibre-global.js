// MapLibre GL ab Version 6 gibt es nur als ES-Modul. Dieses Modul stellt es wie früher als window.maplibregl
// bereit. Kartenskripte, die maplibregl brauchen, werden danach ebenfalls als Modul geladen (gleiche Reihenfolge).
import * as maplibregl from './vendor/maplibre/maplibre-gl.mjs';

window.maplibregl = maplibregl;
