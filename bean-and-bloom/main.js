/* ============================================
   Bean & Bloom — Main JavaScript
   ============================================ */

(function () {
  'use strict';

  // Category icons for menu cards
  const CATEGORY_ICONS = {
    coffee: '&#9749;',
    tea: '&#127861;',
    pastries: '&#129360;',
    specials: '&#127807;'
  };

  // ---- Navbar scroll effect ----
  const navbar = document.getElementById('navbar');

  function updateNavbar() {
    if (window.scrollY > 60) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  }

  window.addEventListener('scroll', updateNavbar, { passive: true });
  updateNavbar();

  // ---- Mobile nav toggle ----
  const navToggle = document.getElementById('nav-toggle');
  const navLinks = document.getElementById('nav-links');

  navToggle.addEventListener('click', function () {
    navLinks.classList.toggle('open');
  });

  // Close mobile nav when a link is clicked
  navLinks.querySelectorAll('a').forEach(function (link) {
    link.addEventListener('click', function () {
      navLinks.classList.remove('open');
    });
  });

  // ---- Smooth scroll for anchor links ----
  document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
    anchor.addEventListener('click', function (e) {
      e.preventDefault();
      var targetId = this.getAttribute('href').slice(1);
      var target = document.getElementById(targetId);
      if (target) {
        var offset = navbar.offsetHeight + 10;
        var top = target.getBoundingClientRect().top + window.pageYOffset - offset;
        window.scrollTo({ top: top, behavior: 'smooth' });
      }
    });
  });

  // ---- Load and render menu from menu.json ----
  var menuGrid = document.getElementById('menu-grid');
  var menuItems = [];

  function renderMenu(filter) {
    var filtered = filter === 'all'
      ? menuItems
      : menuItems.filter(function (item) { return item.category === filter; });

    menuGrid.innerHTML = '';

    filtered.forEach(function (item, i) {
      var card = document.createElement('div');
      card.className = 'menu-card';
      card.style.animationDelay = (i * 0.05) + 's';

      card.innerHTML =
        '<div class="menu-card-img">' +
          '<span class="category-icon">' + (CATEGORY_ICONS[item.category] || '') + '</span>' +
        '</div>' +
        '<div class="menu-card-body">' +
          '<div class="menu-card-header">' +
            '<h3>' + escapeHtml(item.name) + '</h3>' +
            '<span class="menu-card-price">$' + item.price.toFixed(2) + '</span>' +
          '</div>' +
          '<p class="menu-card-desc">' + escapeHtml(item.description) + '</p>' +
          '<span class="menu-card-tag">' + escapeHtml(item.category) + '</span>' +
        '</div>';

      menuGrid.appendChild(card);
    });
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // Fetch menu data
  fetch('menu.json')
    .then(function (res) { return res.json(); })
    .then(function (data) {
      menuItems = data.items || [];
      renderMenu('all');
    })
    .catch(function () {
      menuGrid.innerHTML = '<p style="text-align:center;color:#6B6B6B;">Menu is currently unavailable. Please check back soon.</p>';
    });

  // ---- Menu filter buttons ----
  var filterButtons = document.querySelectorAll('.filter-btn');

  filterButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      filterButtons.forEach(function (b) { b.classList.remove('active'); });
      this.classList.add('active');
      renderMenu(this.getAttribute('data-filter'));
    });
  });

  // ---- Lazy loading for gallery and about images ----
  function initLazyLoading() {
    var lazyElements = document.querySelectorAll('[data-lazy]');

    if ('IntersectionObserver' in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            var el = entry.target;
            var src = el.getAttribute('data-lazy');
            // In production, this would set a background-image from the src.
            // For this demo, we add a loaded class for visual feedback.
            el.classList.add('lazy-loaded');
            el.removeAttribute('data-lazy');
            observer.unobserve(el);
          }
        });
      }, { rootMargin: '100px' });

      lazyElements.forEach(function (el) {
        observer.observe(el);
      });
    } else {
      // Fallback: mark all as loaded
      lazyElements.forEach(function (el) {
        el.classList.add('lazy-loaded');
      });
    }
  }

  initLazyLoading();

  // ---- Contact form validation ----
  var contactForm = document.getElementById('contact-form');
  var formSuccess = document.getElementById('form-success');

  function showError(fieldId, message) {
    var field = document.getElementById(fieldId);
    var errorEl = document.getElementById(fieldId + '-error');
    field.classList.add('error');
    errorEl.textContent = message;
  }

  function clearError(fieldId) {
    var field = document.getElementById(fieldId);
    var errorEl = document.getElementById(fieldId + '-error');
    field.classList.remove('error');
    errorEl.textContent = '';
  }

  function validateEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }

  // Real-time validation on blur
  ['name', 'email', 'message'].forEach(function (fieldId) {
    var field = document.getElementById(fieldId);
    field.addEventListener('blur', function () {
      validateField(fieldId);
    });
    field.addEventListener('input', function () {
      if (field.classList.contains('error')) {
        validateField(fieldId);
      }
    });
  });

  function validateField(fieldId) {
    var field = document.getElementById(fieldId);
    var value = field.value.trim();

    clearError(fieldId);

    if (fieldId === 'name') {
      if (!value) {
        showError('name', 'Please enter your name.');
        return false;
      }
      if (value.length < 2) {
        showError('name', 'Name must be at least 2 characters.');
        return false;
      }
    }

    if (fieldId === 'email') {
      if (!value) {
        showError('email', 'Please enter your email.');
        return false;
      }
      if (!validateEmail(value)) {
        showError('email', 'Please enter a valid email address.');
        return false;
      }
    }

    if (fieldId === 'message') {
      if (!value) {
        showError('message', 'Please enter a message.');
        return false;
      }
      if (value.length < 10) {
        showError('message', 'Message must be at least 10 characters.');
        return false;
      }
    }

    return true;
  }

  contactForm.addEventListener('submit', function (e) {
    e.preventDefault();

    var isValid = true;
    ['name', 'email', 'message'].forEach(function (fieldId) {
      if (!validateField(fieldId)) {
        isValid = false;
      }
    });

    if (!isValid) return;

    // Simulate form submission
    var submitBtn = contactForm.querySelector('button[type="submit"]');
    submitBtn.textContent = 'Sending...';
    submitBtn.disabled = true;

    setTimeout(function () {
      contactForm.reset();
      submitBtn.textContent = 'Send Message';
      submitBtn.disabled = false;
      formSuccess.classList.add('visible');

      setTimeout(function () {
        formSuccess.classList.remove('visible');
      }, 5000);
    }, 1000);
  });

})();
