document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("contact-form");
  const successMsg = document.getElementById("form-success");

  const validators = {
    name: {
      test: (v) => v.trim().length >= 2,
      msg: "Name must be at least 2 characters.",
    },
    email: {
      test: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v),
      msg: "Please enter a valid email address.",
    },
    phone: {
      test: (v) => /^[\d\s()+\-]{7,20}$/.test(v.trim()),
      msg: "Please enter a valid phone number.",
    },
    service: {
      test: (v) => v !== "",
      msg: "Please select a service.",
    },
    "pet-name": {
      test: (v) => v.trim().length >= 1,
      msg: "Please enter your pet's name.",
    },
  };

  function validateField(field) {
    const name = field.name;
    const rule = validators[name];
    if (!rule) return true;

    const errorEl = field.parentElement.querySelector(".error-message");
    const valid = rule.test(field.value);

    field.classList.toggle("invalid", !valid);
    if (errorEl) errorEl.textContent = valid ? "" : rule.msg;

    return valid;
  }

  // Live validation on blur
  Object.keys(validators).forEach((name) => {
    const field = form.elements[name];
    if (field) {
      field.addEventListener("blur", () => validateField(field));
      field.addEventListener("input", () => {
        if (field.classList.contains("invalid")) validateField(field);
      });
    }
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();

    let allValid = true;
    Object.keys(validators).forEach((name) => {
      const field = form.elements[name];
      if (field && !validateField(field)) allValid = false;
    });

    if (!allValid) return;

    form.hidden = true;
    successMsg.hidden = false;
  });
});
