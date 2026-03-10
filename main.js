document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('contact-form');
  if (!form) return;

  const rules = {
    name: {
      validate: (v) => v.trim().length >= 2,
      message: 'Name must be at least 2 characters.',
    },
    email: {
      validate: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim()),
      message: 'Please enter a valid email address.',
    },
    phone: {
      validate: (v) => v.trim() === '' || /^[\d\s\-+()]{7,}$/.test(v.trim()),
      message: 'Please enter a valid phone number.',
    },
    service: {
      validate: (v) => v !== '',
      message: 'Please select a service.',
    },
    message: {
      validate: (v) => v.trim().length >= 10,
      message: 'Message must be at least 10 characters.',
    },
  };

  function validateField(name) {
    const rule = rules[name];
    if (!rule) return true;

    const field = form.elements[name];
    if (!field) return true;

    const group = field.closest('.form-group');
    const errorEl = group.querySelector('.error-msg');
    const valid = rule.validate(field.value);

    if (valid) {
      group.classList.remove('invalid');
    } else {
      group.classList.add('invalid');
      if (errorEl) errorEl.textContent = rule.message;
    }
    return valid;
  }

  // Live validation on blur
  Object.keys(rules).forEach((name) => {
    const field = form.elements[name];
    if (field) {
      field.addEventListener('blur', () => validateField(name));
      field.addEventListener('input', () => {
        const group = field.closest('.form-group');
        if (group.classList.contains('invalid')) {
          validateField(name);
        }
      });
    }
  });

  form.addEventListener('submit', (e) => {
    e.preventDefault();

    let allValid = true;
    Object.keys(rules).forEach((name) => {
      if (!validateField(name)) allValid = false;
    });

    if (!allValid) return;

    // Show success message
    form.style.display = 'none';
    const success = document.querySelector('.form-success');
    if (success) success.style.display = 'block';
  });
});
