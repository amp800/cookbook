// Shared helpers for the Cookbook site (home, import, and recipe pages).
// Loaded from _layouts/default.html so every page can use them.

function getPAT() {
  return localStorage.getItem('gh_pat') || '';
}

function blobToBase64(blob) {
  return new Promise(function (resolve, reject) {
    var reader = new FileReader();
    reader.onload = function () {
      resolve(String(reader.result).split(',')[1]); // strip the data URL prefix
    };
    reader.onerror = function () { reject(new Error('Could not read the image data')); };
    reader.readAsDataURL(blob);
  });
}

// Downscale and re-encode any image file to a JPEG blob, so photo imports and
// hero-image replacements keep repo uploads small and fast.
function compressImageToJpeg(file, maxDim, quality) {
  maxDim = maxDim || 1600;
  quality = quality || 0.85;
  return new Promise(function (resolve, reject) {
    var url = URL.createObjectURL(file);
    var img = new Image();
    img.onload = function () {
      URL.revokeObjectURL(url);
      var scale = Math.min(1, maxDim / Math.max(img.width, img.height));
      var canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(img.width * scale));
      canvas.height = Math.max(1, Math.round(img.height * scale));
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(function (blob) {
        if (blob) resolve(blob);
        else reject(new Error('Could not compress that image — try a smaller one'));
      }, 'image/jpeg', quality);
    };
    img.onerror = function () {
      URL.revokeObjectURL(url);
      reject(new Error('Could not read that image'));
    };
    img.src = url;
  });
}

// Tag autocomplete. The page must define EXISTING_TAGS (the build-time tag
// list) before a suggestion list can be shown.
function setupTagAutocomplete(inputId) {
  var input = document.getElementById(inputId);
  if (!input) return;

  var wrap = document.createElement('div');
  wrap.className = 'tag-suggest-wrap';
  input.parentNode.insertBefore(wrap, input.nextSibling);

  var list = document.createElement('div');
  list.className = 'tag-suggest';
  list.style.display = 'none';
  wrap.appendChild(list);

  var matches = [];
  var active = -1;

  // Find where the token being typed begins (after the last space or comma)
  // so only that token is replaced when a suggestion is picked.
  function tokenStart() {
    var v = input.value;
    var i = v.length;
    while (i > 0 && v[i - 1] !== ' ' && v[i - 1] !== ',') i--;
    return i;
  }

  function currentToken() {
    return input.value.slice(tokenStart()).trim().toLowerCase();
  }

  function accept(newToken) {
    var lead = input.value.slice(0, tokenStart());
    input.value = lead + newToken;
    hide();
  }

  function show() {
    var tok = currentToken();
    if (!tok) { hide(); return; }
    matches = EXISTING_TAGS.filter(function (t) {
      return t.toLowerCase().indexOf(tok) === 0;
    }).slice(0, 8);
    if (!matches.length) { hide(); return; }
    list.innerHTML = '';
    matches.forEach(function (t, idx) {
      var el = document.createElement('div');
      el.className = 'tag-suggest-item' + (idx === active ? ' active' : '');
      el.textContent = t;
      el.addEventListener('mousedown', function (ev) {
        ev.preventDefault();
        accept(t);
      });
      list.appendChild(el);
    });
    list.style.display = 'block';
  }

  function hide() {
    list.style.display = 'none';
    active = -1;
  }

  input.addEventListener('input', function () { active = -1; show(); });
  input.addEventListener('focus', show);
  input.addEventListener('blur', function () { setTimeout(hide, 120); });
  input.addEventListener('keydown', function (ev) {
    if (list.style.display === 'none') return;
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      active = (active + 1) % matches.length;
      show();
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      active = (active - 1 + matches.length) % matches.length;
      show();
    } else if (ev.key === 'Enter' || ev.key === 'Tab') {
      if (active >= 0 && matches[active]) {
        ev.preventDefault();
        accept(matches[active]);
      }
    } else if (ev.key === 'Escape') {
      hide();
    }
  });
}
