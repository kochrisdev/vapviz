// Fonts are self-hosted (@fontsource, OFL) — same three faces as the app.
import "@fontsource/silkscreen";
import "@fontsource/pixelify-sans";
import "@fontsource/pixelify-sans/500.css";
import "@fontsource/vt323";
import "./style.css";

// Copy-to-clipboard for the pip command.
for (const btn of document.querySelectorAll<HTMLButtonElement>(".copy-btn")) {
  btn.addEventListener("click", async () => {
    const text = btn.dataset.copy ?? "";
    try {
      await navigator.clipboard.writeText(text);
      const old = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => (btn.textContent = old), 1200);
    } catch {
      // Clipboard unavailable (permissions/old browser) — leave the text visible.
    }
  });
}

// Respect reduced motion: hold the hero on its poster frame instead of looping.
const video = document.getElementById("hero-video") as HTMLVideoElement | null;
if (video && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  video.removeAttribute("autoplay");
  video.pause();
}
