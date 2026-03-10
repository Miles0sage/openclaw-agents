# Paws & Claws Pet Grooming

A modern landing page for Paws & Claws pet grooming business.

## Project Structure

```
paws-and-claws/
├── index.html    # Main landing page (hero, services grid, contact form)
├── styles.css    # Modern responsive styling
├── main.js       # Contact form validation
└── README.md     # This file
```

## Features

- **Hero Section** -- Eye-catching introduction with call-to-action
- **Services Grid** -- Six grooming services with icons and pricing
- **Contact Form** -- Appointment booking form with JavaScript validation
- **Responsive Design** -- Works on desktop, tablet, and mobile

## Getting Started

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/paws-and-claws.git
   cd paws-and-claws
   ```

2. Open `index.html` in your browser:
   ```bash
   open index.html
   ```

   Or use a local dev server:
   ```bash
   npx serve .
   ```

No build tools or dependencies required -- pure HTML, CSS, and JavaScript.

## Form Validation

The contact form (`main.js`) validates the following fields:

- **Name** -- Required, minimum 2 characters
- **Email** -- Required, valid email format
- **Phone** -- Required, validates phone number format
- **Service** -- Required, must select a grooming service
- **Pet's Name** -- Required
- **Message** -- Optional, free-text notes

## Services Offered

| Service             | Starting Price |
|---------------------|---------------|
| Full Grooming       | $45           |
| Bath & Brush        | $30           |
| Nail Trimming       | $15           |
| Teeth Cleaning      | $25           |
| De-shedding Treatment | $40         |
| Puppy's First Groom | $25           |

## Browser Support

Works in all modern browsers (Chrome, Firefox, Safari, Edge).

## License

MIT
