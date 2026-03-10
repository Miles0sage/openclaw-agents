# Bean & Bloom

A cozy neighborhood coffee shop website with a botanical garden theme. Built with vanilla HTML, CSS, and JavaScript — no frameworks, no build tools.

## Features

- **Hero Section** — Full-viewport botanical gradient with call-to-action
- **Dynamic Menu** — Loads from `menu.json`, filterable by category (coffee, tea, pastries, specials)
- **About Section** — Cafe story with stats
- **Gallery** — CSS grid mosaic layout with hover effects
- **Contact Form** — Client-side validation with real-time feedback
- **Map Placeholder** — Ready for Google Maps embed
- **Responsive** — Mobile-first breakpoints at 480px, 768px, 992px
- **Smooth Scroll** — Native CSS + JS scroll with active nav highlighting
- **Lazy Loading** — IntersectionObserver-based image lazy loading (ready for real images)

## Project Structure

```
bean-and-bloom/
├── index.html      # Main page with all sections
├── styles.css      # Responsive styles, earthy color palette
├── main.js         # Menu rendering, filtering, form validation, scroll
├── menu.json       # 16 menu items across 4 categories
└── README.md       # This file
```

## Setup

1. Clone or download the project
2. Open `index.html` in a browser — that's it

For local development with live reload:

```bash
# Using Python
python3 -m http.server 8000

# Using Node.js
npx serve .

# Using PHP
php -S localhost:8000
```

Then open `http://localhost:8000` in your browser.

## Customization

### Adding Menu Items

Edit `menu.json`. Each item needs:

```json
{
  "id": 17,
  "name": "Item Name",
  "category": "coffee",
  "description": "Short description of the item.",
  "price": 5.00
}
```

Categories: `coffee`, `tea`, `pastries`, `specials`

### Replacing Placeholder Images

1. Add images to an `images/` directory
2. Replace gallery `<div class="gallery-placeholder">` elements with `<img>` tags
3. Use `data-src` attribute for lazy loading: `<img data-src="images/photo.jpg" alt="...">`

### Embedding Google Maps

Replace the `.map-placeholder` div in `index.html` with:

```html
<iframe
  src="https://www.google.com/maps/embed?pb=YOUR_EMBED_URL"
  width="100%"
  height="300"
  style="border:0; border-radius:12px;"
  allowfullscreen
  loading="lazy">
</iframe>
```

## Deployment

### Static Hosting (Vercel, Netlify, GitHub Pages)

No build step required. Deploy the directory as-is.

**Vercel:**
```bash
npx vercel --prod
```

**Netlify:**
Drag and drop the folder into Netlify's deploy UI, or:
```bash
npx netlify deploy --prod --dir .
```

**GitHub Pages:**
Push to a repo, then Settings > Pages > Source: main branch, root folder.

## Browser Support

Modern browsers (Chrome, Firefox, Safari, Edge). Uses CSS custom properties, CSS Grid, `backdrop-filter`, and `IntersectionObserver`.

## License

MIT
