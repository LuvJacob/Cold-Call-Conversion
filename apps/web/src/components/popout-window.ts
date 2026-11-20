// Pure helpers for the briefing pop-out (Document Picture-in-Picture).
// Kept free of JSX so they can be unit-tested with the node test runner.

export const POPOUT_SIZE = { width: 380, height: 560 };
export const POPOUT_UNSUPPORTED_TIP = "Pop-out needs Chrome or Edge";

export type PipApi = {
  requestWindow: (options?: {
    width?: number;
    height?: number;
  }) => Promise<Window>;
};

export function getPipApi(win: unknown): PipApi | null {
  const api = (win as { documentPictureInPicture?: PipApi } | null | undefined)
    ?.documentPictureInPicture;
  return api && typeof api.requestWindow === "function" ? api : null;
}

export function isPopoutSupported(win: unknown): boolean {
  return getPipApi(win) !== null;
}

/** Copy the page's stylesheets and theme classes into the PiP document. */
export function copyStyles(source: Document, target: Document): void {
  target.documentElement.className = source.documentElement.className;
  target.body.className = source.body.className;
  const theme = source.documentElement.getAttribute("data-theme");
  if (theme) target.documentElement.setAttribute("data-theme", theme);
  for (const node of Array.from(
    source.querySelectorAll('link[rel="stylesheet"], style'),
  )) {
    const clone = node.cloneNode(true) as HTMLElement;
    if (clone instanceof HTMLLinkElement && node instanceof HTMLLinkElement) {
      clone.href = node.href; // absolute, so it resolves in the PiP document
    }
    target.head.appendChild(clone);
  }
}

export async function openPopout(win: unknown): Promise<Window | null> {
  const api = getPipApi(win);
  if (!api) return null;
  return api.requestWindow(POPOUT_SIZE);
}
