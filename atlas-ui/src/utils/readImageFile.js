/** Raster-only logo uploads (no SVG — XSS / unpredictable render). */

export const LOGO_ACCEPT =
  "image/png,image/jpeg,image/webp,image/gif,.png,.jpg,.jpeg,.webp,.gif";

const RASTER_EXT = /\.(png|jpe?g|webp|gif)$/i;
const BLOCKED_EXT = /\.svg$/i;

/** True for common raster image MIME types or extensions. */
export function isImageFile(file) {
  if (!file) return false;
  const name = file.name || "";
  if (BLOCKED_EXT.test(name) || (file.type || "").includes("svg")) return false;
  if (file.type && file.type.startsWith("image/")) return true;
  return RASTER_EXT.test(name);
}

/** Read an image file as raw base64 (no data-URL prefix). */
export function readImageFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    if (!isImageFile(file)) {
      reject(new Error("Use a PNG, JPEG, WebP, or GIF logo (SVG is not supported)."));
      return;
    }
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
    reader.onerror = () =>
      reject(reader.error || new Error("Could not read image"));
    reader.readAsDataURL(file);
  });
}
