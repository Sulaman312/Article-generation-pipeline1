const IMAGE_EXT = /\.(png|jpe?g|webp|gif|svg)$/i;

/** True for common image MIME types or file extensions (Windows may omit MIME). */
export function isImageFile(file) {
  if (!file) return false;
  if (file.type && file.type.startsWith("image/")) return true;
  return IMAGE_EXT.test(file.name || "");
}

/** Read an image file as raw base64 (no data-URL prefix). */
export function readImageFileAsBase64(file) {  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Could not read image"));
        return;
      }
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error || new Error("Could not read image"));
    reader.readAsDataURL(file);
  });
}
