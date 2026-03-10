/* ===========================
   Bean & Bloom — Main JS
   =========================== */

(function () {
  'use strict';

  // ---- Menu Data & Rendering ----

  const menuGrid = document.getElementById('menu-grid');
  let menuItems = [];

  async function loadMenu() {
    try {
      const response = await fetch('menu.json');
      const data = await response.json();
      menuItems = data.items;
      renderMenu('all');
    } catch (err) {
      menuGrid.innerHTML = '<p style="text-align:center;color:#6b6560;">Menu is currently unavailable.</p>';
    }
  }

  function renderMenu(filter) {
    const filtered = filter === 'all'
      ? menuItems
      : menuItems.filter(item => item.category === filter);

    menuGrid.innerHTML = filtered.map((item, i) => `
      <div class="menu-card fade-in" style="animation-delay: ${i * 0.05}s">
        <span class="menu-card-category">${item.category}</span>
        <div class="menu-card-header">
          <span class="menu-card-name">${item.name}</span>
          <span class="menu-card-price">$${item.price.toFixed(2)}</span>
        </div>
        <p class="menu-card-desc">${item.description}</p>
      </div>
    `).join('');
  }

  // ---- Menu Filtering ----

  const filterButtons = document.querySelectorAll('.filter-btn');

  filterButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      filterButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderMenu(btn.dataset.filter);
    });
  });

  // ---- Smooth Scroll Navigation ----

  document.querySelectorAll('a[href^="#"]').forEach(link => {
    link.addEventListener('click', (e) => {
      const target = document.querySelector(link.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth' });

        // Close mobile nav if open
        navLinks.classList.remove('open');
      }
    });
  });

  // ---- Navbar Scroll Effect ----

  const navbar = document.getElementById('navbar');

  window.addEventListener('scroll', () => {
    navbar.classList.toggle('scrolled', window.scrollY > 50);
    updateActiveNav();
  }, { passive: true });

  // ---- Active Nav Link Highlighting ----

  const sections = document.querySelectorAll('.section');
  const navAnchors = document.querySelectorAll('.nav-links a');

  function updateActiveNav() {
    const scrollPos = window.scrollY + 120;

    sections.forEach(section => {
      const top = section.offsetTop;
      const height = section.offsetHeight;
      const id = section.getAttribute('id');

      if (scrollPos >= top && scrollPos < top + height) {
        navAnchors.forEach(a => {
          a.classList.toggle('active', a.getAttribute('href') === `#${id}`);
        });
      }
    });
  }

  // ---- Mobile Navigation Toggle ----

  const navToggle = document.getElementById('nav-toggle');
  const navLinks = document.getElementById('nav-links');

  navToggle.addEventListener('click', () => {
    navLinks.classList.toggle('open');
  });

  // ---- Image Lazy Loading ----

  function setupLazyLoading() {
    const lazyImages = document.querySelectorAll('img[data-src]');
    if (!lazyImages.length) return;

    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            const img = entry.target;
            img.src = img.dataset.src;
            img.removeAttribute('data-src');
            observer.unobserve(img);
          }
        });
      }, { rootMargin: '200px' });

      lazyImages.forEach(img => observer.observe(img));
    } else {
      // Fallback: load all images immediately
      lazyImages.forEach(img => {
        img.src = img.dataset.src;
        img.removeAttribute('data-src');
      });
    }
  }

  // ---- Contact Form Validation ----

  const contactForm = document.getElementById('contact-form');
  const formSuccess = document.getElementById('form-success');

  const validators = {
    name: {
      validate: (v) => v.trim().length >= 2,
      message: 'Please enter your name (at least 2 characters).'
    },
    email: {
      validate: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim()),
      message: 'Please enter a valid email address.'
    },
    message: {
      validate: (v) => v.trim().length >= 10,
      message: 'Please enter a message (at least 10 characters).'
    }
  };

  function validateField(name) {
    const input = contactForm.querySelector(`[name="${name}"]`);
    const errorEl = document.getElementById(`${name}-error`);
    const rule = validators[name];

    if (!rule.validate(input.value)) {
      input.classList.add('invalid');
      errorEl.textContent = rule.message;
      return false;
    }

    input.classList.remove('invalid');
    errorEl.textContent = '';
    return true;
  }

  // Real-time validation on blur
  Object.keys(validators).forEach(name => {
    const input = contactForm.querySelector(`[name="${name}"]`);
    input.addEventListener('blur', () => validateField(name));
    input.addEventListener('input', () => {
      if (input.classList.contains('invalid')) {
        validateField(name);
      }
    });
  });

  contactForm.addEventListener('submit', (e) => {
    e.preventDefault();

    const allValid = Object.keys(validators).every(name => validateField(name));

    if (allValid) {
      // Simulate form submission
      const submitBtn = contactForm.querySelector('.btn-submit');
      submitBtn.textContent = 'Sending...';
      submitBtn.disabled = true;

      setTimeout(() => {
        formSuccess.classList.add('visible');
        contactForm.reset();
        submitBtn.textContent = 'Send Message';
        submitBtn.disabled = false;

        setTimeout(() => formSuccess.classList.remove('visible'), 5000);
      }, 1000);
    }
  });

  // ---- Initialize ----

  loadMenu();
  setupLazyLoading();
  updateActiveNav();
})();
