/**
 * dfs-download.js — save a CSV response the server produced (lazily loaded
 * DFS components only; kept out of the /dfs page chunk).
 */

/** Save ``res``'s body under its Content-Disposition filename. */
export async function saveResponseAsFile(res, fallbackName) {
  const blob = await res.blob();
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "")?.[1] || fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** JSON body of a failed response, or null when it has none. */
export async function errorBody(res) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}
