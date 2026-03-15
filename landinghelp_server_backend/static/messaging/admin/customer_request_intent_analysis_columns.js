(function () {
  'use strict';

  var STORAGE_KEY = 'admin:messaging:customerrequestintentanalysis:columns:v1';

  function getColumnKey(cell) {
    if (!cell || !cell.classList) return '';
    for (var i = 0; i < cell.classList.length; i += 1) {
      var name = cell.classList[i] || '';
      if (name.indexOf('column-') === 0) {
        return name.slice(7);
      }
    }
    return '';
  }

  function getColumnLabel(cell) {
    if (!cell) return '';
    return (cell.textContent || '').trim().replace(/\s+/g, ' ');
  }

  function readState(columns) {
    var fallbackOrder = columns.map(function (column) { return column.key; });
    var fallbackVisible = {};
    columns.forEach(function (column) { fallbackVisible[column.key] = true; });

    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return { order: fallbackOrder, visible: fallbackVisible };
      }
      var parsed = JSON.parse(raw);
      var parsedOrder = Array.isArray(parsed.order) ? parsed.order : [];
      var parsedVisible = parsed.visible && typeof parsed.visible === 'object' ? parsed.visible : {};

      var validKeys = new Set(fallbackOrder);
      var filteredOrder = parsedOrder.filter(function (key) { return validKeys.has(key); });
      fallbackOrder.forEach(function (key) {
        if (filteredOrder.indexOf(key) < 0) filteredOrder.push(key);
      });

      var mergedVisible = {};
      fallbackOrder.forEach(function (key) {
        mergedVisible[key] = parsedVisible[key] !== false;
      });

      return { order: filteredOrder, visible: mergedVisible };
    } catch (e) {
      return { order: fallbackOrder, visible: fallbackVisible };
    }
  }

  function writeState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      // noop
    }
  }

  function cloneState(state) {
    return {
      order: (state.order || []).slice(),
      visible: Object.assign({}, state.visible || {})
    };
  }

  function buildDefaultState(columns) {
    return {
      order: columns.map(function (column) { return column.key; }),
      visible: columns.reduce(function (acc, column) {
        acc[column.key] = true;
        return acc;
      }, {})
    };
  }

  function applyLayout(table, state) {
    var headerRow = table.querySelector('thead tr');
    if (!headerRow) return;

    var headerCells = Array.prototype.slice.call(headerRow.children || []);
    var firstHeader = headerCells[0];
    var fixedLeadingCount = firstHeader && firstHeader.classList.contains('action-checkbox-column') ? 1 : 0;

    var keyToIndex = {};
    headerCells.forEach(function (cell, index) {
      var key = getColumnKey(cell);
      if (key) keyToIndex[key] = index;
    });

    var configurableIndexSet = new Set(Object.values(keyToIndex));
    var rows = table.querySelectorAll('thead tr, tbody tr');

    rows.forEach(function (row) {
      var cells = Array.prototype.slice.call(row.children || []);
      if (!cells.length) return;

      var leading = cells.slice(0, Math.min(fixedLeadingCount, cells.length));

      var configMap = {};
      Object.keys(keyToIndex).forEach(function (key) {
        var idx = keyToIndex[key];
        if (idx < cells.length) {
          configMap[key] = cells[idx];
        }
      });

      var trailing = [];
      cells.forEach(function (cell, idx) {
        if (idx < fixedLeadingCount) return;
        if (!configurableIndexSet.has(idx)) trailing.push(cell);
      });

      var orderedConfig = state.order
        .map(function (key) { return configMap[key]; })
        .filter(function (cell) { return !!cell; });

      var nextOrder = leading.concat(orderedConfig, trailing);
      nextOrder.forEach(function (cell) {
        row.appendChild(cell);
      });

      orderedConfig.forEach(function (cell) {
        var key = getColumnKey(cell);
        var visible = state.visible[key] !== false;
        cell.style.display = visible ? '' : 'none';
      });
    });

    autosizeOriginalTextTextareas(table);
  }

  function autosizeOriginalTextTextareas(table) {
    if (!table) return;
    var textareas = table.querySelectorAll('tbody td.field-original_text textarea');
    textareas.forEach(function (textarea) {
      if (!textarea) return;

      textarea.style.width = '100%';
      textarea.style.minHeight = '30px';
      textarea.style.resize = 'vertical';
      textarea.style.overflowY = 'hidden';
      textarea.rows = 1;

      var resize = function () {
        textarea.style.height = 'auto';
        var target = Math.max(30, Math.min(textarea.scrollHeight, 140));
        textarea.style.height = target + 'px';
      };

      if (!textarea.dataset.autosizeBound) {
        textarea.addEventListener('input', resize);
        textarea.dataset.autosizeBound = '1';
      }
      resize();
    });
  }

  function buildPopupControl(columns, getCurrentState, onApply, onReset) {
    var triggerBtn = document.createElement('button');
    triggerBtn.type = 'button';
    triggerBtn.className = 'button';
    triggerBtn.setAttribute('aria-label', '컬럼 필터 열기');
    triggerBtn.setAttribute('title', '컬럼 필터');
    triggerBtn.style.display = 'inline-flex';
    triggerBtn.style.alignItems = 'center';
    triggerBtn.style.justifyContent = 'center';
    triggerBtn.style.width = '34px';
    triggerBtn.style.height = '32px';
    triggerBtn.style.padding = '0';
    triggerBtn.style.marginLeft = '6px';
    triggerBtn.innerHTML = (
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
      + '<path d="M3 5H21L14 13V19L10 21V13L3 5Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
      + '</svg>'
    );

    var overlay = document.createElement('div');
    overlay.style.display = 'none';
    overlay.style.position = 'fixed';
    overlay.style.inset = '0';
    overlay.style.background = 'rgba(0, 0, 0, 0.5)';
    overlay.style.zIndex = '9999';

    var modal = document.createElement('div');
    modal.className = 'module';
    modal.style.position = 'absolute';
    modal.style.top = '10%';
    modal.style.left = '50%';
    modal.style.transform = 'translateX(-50%)';
    modal.style.width = 'min(560px, calc(100% - 32px))';
    modal.style.maxHeight = '80vh';
    modal.style.overflow = 'auto';

    var inner = document.createElement('div');
    inner.style.padding = '12px';

    var title = document.createElement('strong');
    title.textContent = '컬럼 필터';
    inner.appendChild(title);

    var help = document.createElement('div');
    help.textContent = '팝업에서 표시 컬럼과 순서를 설정하세요.';
    help.style.margin = '6px 0 8px';
    help.style.opacity = '0.85';
    inner.appendChild(help);

    var list = document.createElement('div');
    list.style.display = 'grid';
    list.style.rowGap = '6px';
    inner.appendChild(list);

    var draftState = cloneState(getCurrentState());

    function move(key, delta) {
      var idx = draftState.order.indexOf(key);
      if (idx < 0) return;
      var next = idx + delta;
      if (next < 0 || next >= draftState.order.length) return;
      var copy = draftState.order.slice();
      var temp = copy[idx];
      copy[idx] = copy[next];
      copy[next] = temp;
      draftState.order = copy;
      renderRows();
    }

    function renderRows() {
      list.innerHTML = '';
      draftState.order.forEach(function (key) {
        var column = columns.find(function (item) { return item.key === key; });
        if (!column) return;

        var row = document.createElement('div');
        row.style.display = 'flex';
        row.style.alignItems = 'center';
        row.style.gap = '8px';

        var checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = draftState.visible[key] !== false;
        checkbox.addEventListener('change', function () {
          draftState.visible[key] = checkbox.checked;
        });
        row.appendChild(checkbox);

        var label = document.createElement('span');
        label.textContent = column.label || key;
        label.style.minWidth = '240px';
        row.appendChild(label);

        var upBtn = document.createElement('button');
        upBtn.type = 'button';
        upBtn.textContent = '↑';
        upBtn.className = 'button';
        upBtn.addEventListener('click', function () { move(key, -1); });
        row.appendChild(upBtn);

        var downBtn = document.createElement('button');
        downBtn.type = 'button';
        downBtn.textContent = '↓';
        downBtn.className = 'button';
        downBtn.addEventListener('click', function () { move(key, 1); });
        row.appendChild(downBtn);

        list.appendChild(row);
      });
    }

    function openPopup() {
      draftState = cloneState(getCurrentState());
      renderRows();
      overlay.style.display = '';
    }

    function closePopup() {
      overlay.style.display = 'none';
    }

    var actions = document.createElement('div');
    actions.style.display = 'flex';
    actions.style.gap = '8px';
    actions.style.marginTop = '10px';

    var applyBtn = document.createElement('button');
    applyBtn.type = 'button';
    applyBtn.textContent = '적용';
    applyBtn.className = 'button default';
    applyBtn.addEventListener('click', function () {
      onApply(cloneState(draftState));
      closePopup();
    });
    actions.appendChild(applyBtn);

    var resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.textContent = '초기화';
    resetBtn.className = 'button';
    resetBtn.addEventListener('click', function () {
      var resetState = onReset();
      draftState = cloneState(resetState);
      renderRows();
    });
    actions.appendChild(resetBtn);

    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.textContent = '닫기';
    closeBtn.className = 'button';
    closeBtn.addEventListener('click', closePopup);
    actions.appendChild(closeBtn);

    inner.appendChild(actions);
    modal.appendChild(inner);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    triggerBtn.addEventListener('click', openPopup);
    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) {
        closePopup();
      }
    });

    return triggerBtn;
  }

  function initialize() {
    var table = document.querySelector('#result_list');
    if (!table) return;

    var headerCells = Array.prototype.slice.call(table.querySelectorAll('thead tr th') || []);
    var columns = headerCells
      .map(function (cell) {
        return {
          key: getColumnKey(cell),
          label: getColumnLabel(cell)
        };
      })
      .filter(function (column) { return !!column.key; });

    if (!columns.length) return;

    var state = readState(columns);

    function applyAndSave(nextState) {
      state = cloneState(nextState);
      applyLayout(table, nextState);
      writeState(nextState);
    }

    function resetState() {
      state = buildDefaultState(columns);
      applyAndSave(state);
      return state;
    }

    var host = document.querySelector('#changelist-form') || document.querySelector('#changelist');
    if (!host) return;

    var filterTrigger = buildPopupControl(
      columns,
      function () { return state; },
      applyAndSave,
      resetState,
    );

    var searchForm = document.querySelector('#changelist-search');
    var searchSubmit = searchForm ? searchForm.querySelector('input[type="submit"], button[type="submit"]') : null;
    if (searchForm) {
      if (searchSubmit && searchSubmit.parentNode) {
        searchSubmit.parentNode.insertBefore(filterTrigger, searchSubmit.nextSibling);
      } else {
        searchForm.appendChild(filterTrigger);
      }
    } else {
      host.insertBefore(filterTrigger, host.firstChild);
    }

    applyAndSave(state);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }
})();
