/* =========================================================
   ChromaSky · 火烧云指数预报
   交互脚本：倒计时 / 灯箱 / 更新任务 / 图片兜底
   原生 JS，无任何外部依赖。
   ========================================================= */

(function () {
    'use strict';

    var TICK_MS = 30000;

    /* ---------- 共用：服务器时间基准 ---------- */

    var nowMeta = document.querySelector('meta[name="ck-now"]');
    var serverAtLoad = nowMeta ? Date.parse(nowMeta.getAttribute('content') || '') : NaN;
    var loadStamp = Date.now();
    // 用服务端时间校准本地时钟偏差，避免客户端时间不准导致倒计时错乱
    var clockSkew = Number.isFinite(serverAtLoad) ? serverAtLoad - loadStamp : 0;

    function now() {
        return Date.now() + clockSkew;
    }

    function formatDuration(ms) {
        var totalMinutes = Math.max(0, Math.round(ms / 60000));
        if (totalMinutes < 1) {
            return '不足 1 分钟';
        }
        var days = Math.floor(totalMinutes / 1440);
        var hours = Math.floor((totalMinutes % 1440) / 60);
        var minutes = totalMinutes % 60;
        if (days > 0) {
            return days + ' 天 ' + hours + ' 小时';
        }
        if (hours > 0) {
            return hours + ' 小时 ' + minutes + ' 分';
        }
        return minutes + ' 分钟';
    }

    /* ---------- 倒计时 ---------- */

    function updateCountdown(el) {
        var start = Date.parse(el.getAttribute('data-start') || '');
        var end = Date.parse(el.getAttribute('data-end') || '');
        if (!Number.isFinite(start) || !Number.isFinite(end)) {
            return;
        }

        var current = now();
        var state;
        var labelText = '';
        var valueText = '';
        var noteText = '';
        var windowText = el.getAttribute('data-window') || '';

        if (current < start) {
            state = 'upcoming';
            labelText = '距开始';
            valueText = formatDuration(start - current);
            noteText = windowText ? '窗口 ' + windowText + ' · 北京时间' : '北京时间';
        } else if (current <= end) {
            state = 'live';
            labelText = '进行中';
            valueText = '剩余 ' + formatDuration(end - current);
            noteText = windowText ? '窗口 ' + windowText + ' · 北京时间' : '北京时间';
        } else {
            state = 'past';
            labelText = '时间窗口';
            valueText = windowText || '已结束';
            noteText = '已结束 · 北京时间';
        }

        el.setAttribute('data-state', state);

        var label = el.querySelector('[data-countdown-label]');
        var value = el.querySelector('[data-countdown-value]');
        var note = el.querySelector('[data-countdown-note]');

        if (label) {
            label.textContent = labelText;
        }
        if (value) {
            value.textContent = valueText;
        } else if (!label && !note) {
            el.textContent = valueText;
        }
        if (note) {
            note.textContent = noteText;
        }
    }

    function updateAllCountdowns() {
        var nodes = document.querySelectorAll('[data-countdown]');
        for (var i = 0; i < nodes.length; i += 1) {
            updateCountdown(nodes[i]);
        }
    }

    /* ---------- Toast ---------- */

    var toastRegion = document.getElementById('toast-region');

    function showToast(message, tone) {
        if (!toastRegion) {
            return;
        }
        var kind = tone === 'success' || tone === 'error' ? tone : 'info';
        var toast = document.createElement('div');
        toast.className = 'toast toast--' + kind;
        toast.textContent = message;
        toastRegion.appendChild(toast);

        window.requestAnimationFrame(function () {
            toast.classList.add('is-visible');
        });

        var remove = function () {
            toast.classList.remove('is-visible');
            window.setTimeout(function () {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 260);
        };

        window.setTimeout(remove, 6000);
        toast.addEventListener('click', remove);
    }

    /* ---------- 触发后台更新 ---------- */

    function triggerJob(button) {
        if (!button || button.dataset.busy === 'true') {
            return;
        }

        var label = button.querySelector('[data-btn-label]');
        var originalLabel = label ? label.textContent : '';

        button.dataset.busy = 'true';
        button.disabled = true;
        button.classList.add('is-loading');
        button.setAttribute('aria-busy', 'true');
        if (label) {
            label.textContent = '更新中…';
        }

        fetch('/trigger-job', {
            method: 'POST',
            headers: { 'Accept': 'application/json' }
        }).then(function (response) {
            return response.json().catch(function () {
                return {};
            }).then(function (payload) {
                if (!response.ok) {
                    var detail = payload && payload.detail ? payload.detail : '服务返回 ' + response.status;
                    throw new Error(detail);
                }
                return payload;
            });
        }).then(function (payload) {
            var message = (payload && payload.message)
                ? payload.message
                : '更新任务已在后台开始运行，稍后刷新页面即可查看结果。';
            showToast(message, 'success');
        }).catch(function (error) {
            var reason = error && error.message ? error.message : '网络异常';
            showToast('触发更新失败：' + reason, 'error');
        }).finally(function () {
            delete button.dataset.busy;
            button.disabled = false;
            button.classList.remove('is-loading');
            button.removeAttribute('aria-busy');
            if (label) {
                label.textContent = originalLabel;
            }
        });
    }

    /* ---------- 灯箱 ---------- */

    var dialog = document.getElementById('lightbox');
    var lightboxImg = dialog ? dialog.querySelector('[data-lightbox-img]') : null;
    var lightboxCaption = dialog ? dialog.querySelector('[data-lightbox-caption]') : null;
    var lightboxMedia = dialog ? dialog.querySelector('.lightbox-media') : null;
    var supportsDialog = !!(dialog && typeof dialog.showModal === 'function');
    var lastTrigger = null;

    function clearLightboxFallback() {
        if (!lightboxMedia) {
            return;
        }
        var existing = lightboxMedia.querySelector('.lightbox-fallback');
        if (existing && existing.parentNode) {
            existing.parentNode.removeChild(existing);
        }
        if (lightboxImg) {
            lightboxImg.style.visibility = '';
        }
    }

    function showLightboxFallback() {
        if (!lightboxMedia) {
            return;
        }
        if (lightboxImg) {
            lightboxImg.style.visibility = 'hidden';
        }
        if (!lightboxMedia.querySelector('.lightbox-fallback')) {
            var note = document.createElement('p');
            note.className = 'lightbox-fallback';
            note.textContent = '大图加载失败，请稍后重试。';
            lightboxMedia.appendChild(note);
        }
    }

    function openLightbox(trigger) {
        if (!supportsDialog) {
            return false;
        }
        var src = trigger.getAttribute('data-lightbox-src') || trigger.getAttribute('href');
        if (!src) {
            return false;
        }

        lastTrigger = trigger;
        clearLightboxFallback();

        if (lightboxImg) {
            lightboxImg.setAttribute('src', src);
            lightboxImg.setAttribute('alt', trigger.getAttribute('data-lightbox-alt') || '');
        }
        if (lightboxCaption) {
            lightboxCaption.textContent = trigger.getAttribute('data-lightbox-caption') || '综合指数图';
        }

        if (!dialog.open) {
            dialog.showModal();
        }
        document.body.classList.add('has-lightbox');
        return true;
    }

    function closeLightbox() {
        if (dialog && dialog.open) {
            dialog.close();
        }
    }

    document.addEventListener('click', function (event) {
        var target = event.target;
        if (!(target instanceof Element)) {
            return;
        }

        var trigger = target.closest('[data-lightbox]');
        if (trigger) {
            if (openLightbox(trigger)) {
                event.preventDefault();
            }
            return;
        }

        if (target.closest('[data-lightbox-close]')) {
            closeLightbox();
            return;
        }

        var jobButton = target.closest('[data-trigger-job]');
        if (jobButton) {
            event.preventDefault();
            triggerJob(jobButton);
        }
    });

    if (dialog) {
        // 点击遮罩（dialog 自身）关闭
        dialog.addEventListener('click', function (event) {
            if (event.target === dialog) {
                closeLightbox();
            }
        });

        dialog.addEventListener('close', function () {
            document.body.classList.remove('has-lightbox');
            if (lastTrigger && typeof lastTrigger.focus === 'function') {
                lastTrigger.focus({ preventScroll: true });
            }
            lastTrigger = null;
        });
    }

    if (lightboxImg) {
        lightboxImg.addEventListener('error', showLightboxFallback);
    }

    /* ---------- 图片加载失败兜底 ---------- */

    function addImageFallback(img) {
        var media = img.closest('.plate-media, .card-media');
        if (!media) {
            img.style.visibility = 'hidden';
            return;
        }
        media.classList.add('is-broken');
        if (!media.querySelector('.media-fallback')) {
            var note = document.createElement('span');
            note.className = 'media-fallback';
            note.textContent = '图片暂不可用，请稍后刷新重试';
            media.appendChild(note);
        }
    }

    document.addEventListener('error', function (event) {
        var target = event.target;
        if (target instanceof HTMLImageElement && target !== lightboxImg) {
            addImageFallback(target);
        }
    }, true);

    /* ---------- 页头滚动阴影 ---------- */

    var header = document.querySelector('[data-site-header]');
    function syncHeader() {
        if (!header) {
            return;
        }
        header.classList.toggle('is-scrolled', window.scrollY > 8);
    }

    /* ---------- 初始化 ---------- */

    function init() {
        updateAllCountdowns();
        window.setInterval(updateAllCountdowns, TICK_MS);

        // 定时器在后台标签页会被节流，回到页面时立即校正一次
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) {
                updateAllCountdowns();
            }
        });

        // 脚本执行前就已经加载失败的图片不会再触发 error 事件，这里补一次检查
        var images = document.querySelectorAll('main img, dialog img');
        for (var i = 0; i < images.length; i += 1) {
            var img = images[i];
            if (img.complete && img.naturalWidth === 0 && img !== lightboxImg) {
                addImageFallback(img);
            }
        }

        syncHeader();
        window.addEventListener('scroll', syncHeader, { passive: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();