# Bean & Bloom

A cozy neighborhood cafe website with a botanical garden theme. Built with vanilla HTML, CSS, and JavaScript — no frameworks, no build tools.

## Features

- **Hero section** with gradient background and call-to-action buttons
- **Dynamic menu** loaded from `menu.json` with category filtering (coffee, tea, pastries, specials)
- **About section** with the cafe story, imagery placeholders, and key stats
- **Gallery grid** with hover effects and lazy loading via Intersection Observer
- **Contact section** with info cards, embedded map placeholder, and validated form
- **Responsive design** that works on mobile, tablet, and desktop
- **Smooth scroll navigation** with a sticky navbar that changes on scroll
- **Earthy color palette** — forest greens, warm browns, and cream tones

## Project Structure

```
bean-and-bloom/
  index.html    — Main page with all sections
  styles.css    — Responsive styles with CSS custom properties
  main.js       — Menu loading, filtering, smooth scroll, form validation
  menu.json     — 16 menu items across 4 categories
  README.md     — This file
```

## Setup

No build step required. Open `index.html` in a browser.

**For menu.json to load**, you need to serve the files over HTTP (fetch won't work with `file://`):

```bash
# Python
python3 -m http.server 8000

# Node.js
npx serve .

# PHP
php -S localhost:8000
```

Then open `http://localhost:8000` in your browser.

## Customization

### Menu items
Edit `menu.json` to add, remove, or modify items. Each item needs:
- `id` — unique number
- `name` — display name
- `category` — one of: coffee, tea, pastries, specials
- `description` — short description
- `price` — number (e.g., 5.50)

### Images
Replace the placeholder `div` elements with actual `<img>` tags or set CSS `background-image` on gallery and about image containers. The `data-lazy` attributes are ready for lazy loading real images.

### Map
Replace the `.map-placeholder` div in `index.html` with a real embed (Google Maps, Mapbox, etc.).

### Colors
All colors are defined as CSS custom properties in `:root` at the top of `styles.css`.

## Deployment

### Vercel
```bash
npm i -g vercel
cd bean-and-bloom
vercel
```

### Netlify
Drag and drop the `bean-and-bloom` folder onto [app.netlify.com/drop](https://app.netlify.com/drop).

### GitHub Pages
1. Push the folder to a GitHub repo
2. Go to Settings > Pages
3. Set source to the branch containing the files
4. Site will be live at `https://<username>.github.io/<repo>/`

### Any static host
Upload all files to the root of your web server. No server-side processing needed.

## Browser Support

Works in all modern browsers (Chrome, Firefox, Safari, Edge). Uses Intersection Observer for lazy loading with a fallback for older browsers.
