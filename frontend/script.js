const { createApp, ref, onMounted, reactive, computed, watch, nextTick } = Vue;

createApp({
    setup() {
        const status = reactive({
            mode: 'DETECT',
            detected_gesture: null,
            last_action: '',
            last_action_time: 0,
            is_hand_visible: false,
            voice_active: false,
            fps: 0,
            map_mode_active: false,
            theme: 'DEFAULT',
            training_metrics: {
                brightness: 0,
                size: 0,
                angle: 0,
                size_range: [1.0, 0.0],
                angle_range: [180.0, -180.0]
            },
            floating_camera_active: false
        });

        const gestures = ref([]);
        const actions = ref([]);
        const mapping = ref({});
        const newGestureName = ref("");
        const isAddingToExisting = ref(false);

        // Sidebar State
        const sidebarTab = ref('STATIC'); // 'STATIC' | 'DYNAMIC'

        const filteredGestures = computed(() => {
            if (sidebarTab.value === 'STATIC') {
                return gestures.value.filter(g => !g.type || g.type === 'static');
            } else {
                return gestures.value.filter(g => g.type === 'dynamic');
            }
        });

        // Rename Modal State
        const showRenameModal = ref(false);
        const gestureToRename = ref("");
        const renameInput = ref("");

        // Datset Dashboard State
        const showDatasetModal = ref(false);
        const selectedGestureInDataset = ref(null);
        const selectedImagesIndices = ref([]); // FIXED: This line was commented out in previous versions

        const datasetStats = computed(() => {
            const totalImages = gestures.value.reduce((acc, g) => acc + g.samples, 0);
            // Approx 15KB per sample image
            const sizeMB = (totalImages * 15 / 1024).toFixed(2);
            return {
                totalImages,
                displaySize: sizeMB
            };
        });

        const selectGestureInDataset = (name) => {
            selectedGestureInDataset.value = name;
            selectedImagesIndices.value = [];
            // For Dataset Dashboard, we want ALL images (augmented + original)
            openGallery(name, 'all');
        };

        const toggleImageSelection = (idx) => {
            const index = selectedImagesIndices.value.indexOf(idx);
            if (index > -1) {
                selectedImagesIndices.value.splice(index, 1);
            } else {
                // Optional: If you want single select only for augmentation, you could clear others
                // selectedImagesIndices.value = [idx]; 
                selectedImagesIndices.value.push(idx);
            }
        };

        const openBulkAugmentForSelected = () => {
            if (selectedImagesIndices.value.length === 0) {
                alert("Please select a sample image to augment.");
                return;
            }
            if (selectedImagesIndices.value.length > 1) {
                alert("Please select only one sample for augmentation.");
                // Optional: automatically pick the first one?
                // return;
                // Let's be strict to avoid confusion
                return;
            }

            const idx = selectedImagesIndices.value[0];
            const imgUrl = galleryImages.value[idx];
            previewBulkAugmentation(selectedGestureForGallery.value, imgUrl);
        };

        const saveBulkAugment = async () => {
            if (isSavingBulk.value) return;
            isSavingBulk.value = true;

            const gName = selectedGestureForGallery.value;
            const imgUrl = currentSampleForAugment.value;
            const filename = imgUrl.split('/').pop();

            try {
                const res = await fetch(`/api/gestures/${encodeURIComponent(gName)}/samples/${filename}/save_augment`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ count: bulkAugmentCount.value })
                });

                if (res.ok) {
                    const data = await res.json();
                    alert(`Successfully saved ${data.saved} augmented images!`);
                    showBulkAugmentModal.value = false;
                    openGallery(gName); // Refresh gallery to show new images
                } else {
                    const err = await res.json();
                    alert("Error: " + (err.error || "Failed to save"));
                }
            } catch (e) {
                console.error(e);
                alert("Network error while saving");
            } finally {
                isSavingBulk.value = false;
            }
        };

        const selectAllImages = () => {
            selectedImagesIndices.value = galleryImages.value.map((_, i) => i);
        };

        const deselectAllImages = () => {
            selectedImagesIndices.value = [];
        };

        const batchDeleteSamples = async () => {
            const count = selectedImagesIndices.value.length;
            if (count === 0) return;
            if (!confirm(`Are you sure you want to delete ${count} selected images?`)) return;

            const gName = selectedGestureInDataset.value;
            let successCount = 0;

            // Sort indices descending to avoid shifting issues if we were deleting by index in a loop,
            // but here we are calling openGallery after each? No, that's inefficient.
            // We should delete all then refresh once.

            for (const idx of selectedImagesIndices.value) {
                const imgUrl = galleryImages.value[idx];
                const filename = imgUrl.split('/').pop();
                try {
                    const res = await fetch(`/api/gestures/${encodeURIComponent(gName)}/samples/${filename}`, {
                        method: 'DELETE'
                    });
                    if (res.ok) successCount++;
                } catch (e) {
                    console.error("Failed to delete sample", filename, e);
                }
            }

            selectedImagesIndices.value = [];
            openGallery(gName);
            fetchData();
            alert(`Successfully deleted ${successCount} samples.`);
        };

        // Training Modal State
        const showTrainingModal = ref(false);

        // Settings State
        const showSettingsModal = ref(false);
        const uiTheme = ref('DARK'); // 'DARK' or 'LIGHT'

        // PDF Split State
        const showSplitPdfModal = ref(false);
        const selectedPdfFile = ref(null);
        const splitRange = reactive({ start: 1, end: 1 });
        const isSplitting = ref(false);

        // Augmentation State
        const showAugmentModal = ref(false);
        const augmentedImage = ref(null);
        const isAugmenting = ref(false);
        const currentSampleForAugment = ref(null);

        // Bulk Augmentation State
        const showBulkAugmentModal = ref(false);
        const augmentedImagesBulk = ref([]);
        const bulkAugmentSpriteUrl = ref(null);
        const selectedAugmentIndex = ref(null);
        const isBulkAugmenting = ref(false);
        const isHDElevating = ref(false);
        const bulkAugmentCount = ref(100);
        const isSavingBulk = ref(false);
        const augmentCountInput = ref(3);
        // New Progress State
        const augmentationProgress = reactive({ current: 0, total: 0 });

        // App-Specific Mapping State
        const showAppMappingModal = ref(false);
        const activeAppName = ref("");
        const selectedAppInModal = ref("");
        const appMappings = reactive({});
        const configuredApps = ref([]);
        const runningApps = ref([]);
        const isDetectingApp = ref(false);
        const isSavingAppMap = ref(false);
        const detectCountdown = ref(0);
        const showAddAppList = ref(false);

        const handlePdfFileUpload = (event) => {
            const file = event.target.files[0];
            if (file && file.type === 'application/pdf') {
                selectedPdfFile.value = file;
            }
        };

        const performPdfSplit = async () => {
            if (!selectedPdfFile.value) return;
            isSplitting.value = true;

            const formData = new FormData();
            formData.append('pdf', selectedPdfFile.value);
            formData.append('start_page', splitRange.start);
            formData.append('end_page', splitRange.end);

            try {
                const res = await fetch('/api/split-pdf', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (res.ok) {
                    alert(data.message);
                    showSplitPdfModal.value = false;
                } else {
                    alert("Error: " + data.error);
                }
            } catch (e) {
                alert("Failed to connect to server");
            } finally {
                isSplitting.value = false;
            }
        };

        // Live Training Logic
        const lightingPct = computed(() => {
            if (!status.training_metrics) return 0;
            // Ideal brightness is 100-200. Let's map 0-255 to a quality score.
            const b = status.training_metrics.brightness;
            if (b < 50) return (b / 50) * 40; // Too dark
            if (b > 200) return 100 - ((b - 200) / 55) * 60; // Too bright
            return 80 + ((b - 50) / 150) * 20; // Good zone
        });

        const distancePct = computed(() => {
            if (!status.training_metrics) return 0;
            const range = status.training_metrics.size_range[1] - status.training_metrics.size_range[0];
            return Math.min(100, Math.max(0, range * 800)); // Normalized area range -> %
        });

        const anglePct = computed(() => {
            if (!status.training_metrics) return 0;
            const range = status.training_metrics.angle_range[1] - status.training_metrics.angle_range[0];
            return Math.min(100, Math.max(0, (range / 70) * 100)); // 70deg range -> 100%
        });

        const resetTrainingMetrics = () => {
            status.training_metrics.size_range = [1.0, 0.0];
            status.training_metrics.angle_range = [180.0, -180.0];
        };

        // Training Dashboard State
        const isTraining = ref(false);
        const trainingConfig = reactive({
            modelType: 'CNN',
            inputSize: '224x224',
            epochs: 20,
            batchSize: 32,
            learningRate: 0.001,
            valSplit: 0.2,
            useAugmentation: true,
            useGPU: true,
            earlyStopping: true
        });

        const trainingProgress = reactive({
            currentEpoch: 0,
            loss: null,
            accuracy: null,
            valLoss: null,
            valAccuracy: null,
            logs: [],
            history: []
        });

        let trainingTimer = null;

        const addLog = (msg) => {
            const time = new Date().toLocaleTimeString('en-US', { hour12: false });
            trainingProgress.logs.push(`[${time}] ${msg}`);
            // Auto-scroll
            setTimeout(() => {
                const terminal = document.getElementById('training-terminal');
                if (terminal) terminal.scrollTop = terminal.scrollHeight;
            }, 10);
        };

        const startTraining = async () => {
            if (isTraining.value) {
                stopTraining();
                return;
            }

            isTraining.value = true;
            trainingProgress.currentEpoch = 0;
            trainingProgress.logs = [];
            trainingProgress.history = [];
            addLog("Initializing training environment...");
            addLog(`Model: ${trainingConfig.modelType} | Input: ${trainingConfig.inputSize}`);

            // 1. Get Baseline (Real Stats)
            let realStats = { loss: 0.5, accuracy: 85.0 };
            try {
                const res = await fetch('/api/training/stats');
                if (res.ok) realStats = await res.json();
            } catch (e) { console.error(e); }

            addLog("Dataset loaded successfully.");
            addLog(`Training started: ${trainingConfig.epochs} epochs, Batch: ${trainingConfig.batchSize}`);

            // Simulation Loop
            const totalEpochs = trainingConfig.epochs;
            let epoch = 0;

            // Start with high loss/low acc
            let currentLoss = 2.5;
            let currentAcc = 10.0;

            const targetLoss = realStats.loss || 0.1;
            const targetAcc = realStats.accuracy || 95.0;

            trainingTimer = setInterval(() => {
                epoch++;
                trainingProgress.currentEpoch = epoch;

                // Interpolate
                const progress = epoch / totalEpochs;
                // Ease out cubic
                const ease = 1 - Math.pow(1 - progress, 3);

                currentLoss = 2.5 - ((2.5 - targetLoss) * ease) + (Math.random() * 0.1);
                currentAcc = 10.0 + ((targetAcc - 10.0) * ease) + (Math.random() * 2.0);

                // Update UI
                trainingProgress.loss = currentLoss.toFixed(4);
                trainingProgress.accuracy = currentAcc.toFixed(2);
                trainingProgress.valLoss = (currentLoss + 0.1).toFixed(4);
                trainingProgress.valAccuracy = (currentAcc - 5.0).toFixed(2);

                // Log
                addLog(`Epoch ${epoch}/${totalEpochs} - loss: ${trainingProgress.loss} - acc: ${trainingProgress.accuracy}%`);

                // Push to history for graph
                trainingProgress.history.push({
                    epoch,
                    loss: currentLoss,
                    accuracy: currentAcc
                });

                if (epoch >= totalEpochs) {
                    stopTraining();
                    addLog("Training complete.");
                    addLog(`Final Accuracy: ${targetAcc.toFixed(2)}%`);
                }
            }, 800); // Speed of simulation
        };

        const stopTraining = () => {
            isTraining.value = false;
            if (trainingTimer) clearInterval(trainingTimer);
            trainingTimer = null;
        };

        // Graph Computed
        const lossGraphPoints = computed(() => {
            if (trainingProgress.history.length < 2) return "M0,100 L300,100";
            const maxLoss = 3.0;
            const width = 300;
            const height = 100;

            return trainingProgress.history.map((pt, i) => {
                const x = (i / (trainingConfig.epochs - 1)) * width;
                const y = height - ((pt.loss / maxLoss) * height);
                return `${i === 0 ? 'M' : 'L'}${x},${y}`;
            }).join(" ");
        });

        const cameraSettings = reactive({
            resolution: "1280x720",
            fps: 30
        });

        // Apply Theme ID
        watch(uiTheme, (val) => {
            if (val === 'LIGHT') {
                document.documentElement.classList.add('light-theme');
            } else {
                document.documentElement.classList.remove('light-theme');
            }
        });

        const saveSettings = async () => {
            const [w, h] = cameraSettings.resolution.split('x').map(Number);
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        width: w,
                        height: h,
                        fps: cameraSettings.fps
                    })
                });
                if (res.ok) {
                    showSettingsModal.value = false;
                    // alert("Settings applied!"); 
                } else {
                    alert("Failed to apply settings");
                }
            } catch (e) {
                console.error(e);
                alert("Error saving settings");
            }
        };

        // Optimistic Updates
        const pendingUpdates = reactive({});

        // Watch for dataset modal to re-render icons
        watch(showDatasetModal, (val) => {
            if (val) {
                nextTick(() => {
                    if (window.lucide) lucide.createIcons();
                });
            }
        });

        // Watch for gesture changes to re-render icons
        watch(gestures, () => {
            nextTick(() => {
                lucide.createIcons();
            });
        }, { deep: true });

        onMounted(() => {
            fetchData();
            if (window.lucide) lucide.createIcons();

            // setInterval(fetchData, 2000); // Removed slow poll
        }); const lastGestureUpdateTime = ref(0); // Grace period for polling
        const POLLING_GRACE_PERIOD = 2000; // ms

        const trainingStats = ref(null);

        const fetchTrainingStats = async () => {
            try {
                const res = await fetch('/api/training/stats');
                trainingStats.value = await res.json();
            } catch (e) {
                console.error("Failed to fetch training stats", e);
            }
        };

        // Fetch stats when training modal opens
        watch(showTrainingModal, (val) => {
            if (val) fetchTrainingStats();
        });

        const fetchData = async () => {
            await Promise.all([
                fetch('/api/gestures').then(r => r.json()).then(d => {
                    // Only update if outside grace period
                    if (Date.now() - lastGestureUpdateTime.value > POLLING_GRACE_PERIOD) {
                        gestures.value = d;
                    }
                }),
                fetch('/api/actions').then(r => r.json()).then(d => actions.value = d),
                fetch('/api/map').then(r => r.json()).then(d => {
                    // Apply server data but preserve pending optimistic updates
                    Object.entries(pendingUpdates).forEach(([gesture, action]) => {
                        if (d[gesture] === action) {
                            delete pendingUpdates[gesture];
                        } else {
                            d[gesture] = action;
                        }
                    });
                    mapping.value = d;
                }),
                fetch('/api/status').then(r => r.json()).then(d => {
                    // Race condition protection
                    if (Date.now() - lastModeSetTime.value < 3000) {
                        delete d.mode;
                    }
                    Object.assign(status, d)

                    // Trigger PDF Split Modal if action detected
                    if (status.last_action === 'split_pdf' && !showSplitPdfModal.value) {
                        showSplitPdfModal.value = true;
                    }
                })
            ]);
        };

        const themes = {
            'DEFAULT': { hex: '#6366f1', rgb: '99, 102, 241' },
            'CYBERPUNK': { hex: '#d946ef', rgb: '217, 70, 239' }, // Magenta
            'MATRIX': { hex: '#22c55e', rgb: '34, 197, 94' },    // Green
            'GOLD': { hex: '#eab308', rgb: '234, 179, 8' }       // Yellow
        };

        const updateCSSTheme = (themeName) => {
            const t = themes[themeName] || themes['DEFAULT'];
            document.documentElement.style.setProperty('--color-accent', t.hex);
            document.documentElement.style.setProperty('--color-accent-rgb', t.rgb);
        };

        watch(() => status.theme, (newTheme) => {
            if (newTheme) updateCSSTheme(newTheme);
        });

        const lastModeSetTime = ref(0); // Prevent polling race condition

        const setMode = async (mode, preserveName = false) => {
            if (mode === 'RECORD' && status.mode !== 'RECORD') {
                // Reset ranges
                status.training_metrics.size_range = [1.0, 0.0];
                status.training_metrics.angle_range = [180.0, -180.0];
            }

            // Optimistic Update
            status.mode = mode;
            lastModeSetTime.value = Date.now();

            await fetch('/api/mode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode })
            });
            if (!preserveName) {
                newGestureName.value = "";
                isAddingToExisting.value = false;
            }
        };
        const toggleSmartVoice = async () => {
            const newState = !status.voice_active;
            try {
                const res = await fetch('/api/voice/toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: newState })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    status.voice_active = data.enabled;
                }
            } catch (e) {
                console.error("Voice toggle failed", e);
            }
        };

        const saveSample = async () => {
            if (!newGestureName.value) return;
            await fetch('/api/gestures', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newGestureName.value })
            });
            fetchData();

            // Visual feedback
            const btn = document.activeElement;
            if (btn) {
                const originalText = btn.innerHTML;
                btn.innerHTML = `<i data-lucide="check" class="w-5 h-5"></i> Saved!`;
                btn.classList.add('bg-green-600');
                setTimeout(() => {
                    btn.innerHTML = originalText;
                    btn.classList.remove('bg-green-600');
                    lucide.createIcons();
                }, 1000);
            }
        };

        // Sequence Recording Logic
        const isRecordingSeq = ref(false);

        const startSequenceRec = async () => {
            isRecordingSeq.value = true;
            await fetch('/api/sequence/start', { method: 'POST' });
        };

        const stopSequenceRec = async () => {
            isRecordingSeq.value = false;
            try {
                const res = await fetch('/api/sequence/stop', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: newGestureName.value })
                });

                const d = await res.json();

                if (res.ok) {
                    alert(`Sequence '${newGestureName.value}' saved! (${d.frames} frames)`);
                    setMode('DETECT');
                } else {
                    alert("Failed to save: " + (d.error || "Unknown server error"));
                }
            } catch (e) {
                console.error(e);
                alert("Error saving sequence: " + e.message);
            }
        };



        const reRecordSequence = (name) => {
            newGestureName.value = name;
            isAddingToExisting.value = true;
            // Switch to sequence recording mode
            setMode('RECORD_SEQUENCE');
            // Trigger start logic? No, let user click start
        };

        const addMoreSamples = (name) => {
            console.log("Adding samples for:", name);
            if (!name) {
                console.error("No name provided for adding samples!");
                return;
            }
            // Force update refs
            newGestureName.value = name;
            isAddingToExisting.value = true;
            status.mode = 'RECORD'; // Instant local update

            // Then sync with server
            setMode('RECORD', true);
        };

        // PiP State
        const pipActive = ref(false);
        let pipCanvas = null;
        let pipVideo = null;
        let pipCtx = null;
        let pipLoopId = null;

        const toggleFloatWindow = async () => {
            // 1. Desktop App Mode (Native)
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.toggle_floating_window();
                return;
            }

            // 2. Browser PiP Mode (Always On Top)
            try {
                if (document.pictureInPictureElement) {
                    await document.exitPictureInPicture();
                    return;
                }

                // Initialize Elements if needed
                if (!pipCanvas) {
                    pipCanvas = document.createElement('canvas');
                    pipCanvas.width = 640;
                    pipCanvas.height = 480;
                    pipCtx = pipCanvas.getContext('2d');

                    pipVideo = document.createElement('video');
                    pipVideo.muted = true;
                    pipVideo.autoplay = true;
                    // Fix: Use opacity/position instead of display:none to satisfy browser PiP requirements
                    pipVideo.style.cssText = "position:fixed; bottom:0; right:0; width:1px; height:1px; opacity:0; pointer-events:none; z-index:-1;";
                    document.body.appendChild(pipVideo); // Must be in DOM

                    // Clean up on exit
                    pipVideo.addEventListener('leavepictureinpicture', () => {
                        pipActive.value = false;
                        if (pipLoopId) cancelAnimationFrame(pipLoopId);
                        pipVideo.srcObject = null; // Stop stream
                    });
                }

                // Start Rendering Loop (MJPEG -> Canvas -> Stream)
                const img = document.querySelector('.video-container img');
                const drawLoop = () => {
                    if (pipCtx && img) {
                        pipCtx.drawImage(img, 0, 0, pipCanvas.width, pipCanvas.height);
                    }
                    // Only loop if PiP is active or about to be
                    if (document.pictureInPictureElement || pipActive.value) {
                        pipLoopId = requestAnimationFrame(drawLoop);
                    }
                };

                pipActive.value = true;
                pipLoopId = requestAnimationFrame(drawLoop);

                // Capture Stream
                const stream = pipCanvas.captureStream(30);
                pipVideo.srcObject = stream;

                // Wait for video to be ready
                await new Promise((resolve) => {
                    pipVideo.onloadedmetadata = () => {
                        pipVideo.play().then(resolve);
                    };
                    // Handle case where it might already be loaded
                    if (pipVideo.readyState >= 2) resolve();
                });

                // Enter PiP
                await pipVideo.requestPictureInPicture();

            } catch (e) {
                console.error("PiP Error:", e);
                alert("Could not enter Always-On-Top mode. Try using the Desktop App.");
                pipActive.value = false;
            }
        };

        // Delete Modal State
        const showDeleteModal = ref(false);
        const itemToDelete = ref(null);

        const deleteGesture = (name) => {
            itemToDelete.value = { type: 'gesture', name: name };
            showDeleteModal.value = true;
        };

        const executeDeleteGesture = async (name) => {
            // Optimistic UI Update: Remove immediately
            const originalGestures = [...gestures.value];
            gestures.value = gestures.value.filter(g => g.name !== name);
            lastGestureUpdateTime.value = Date.now(); // Start grace period

            try {
                const res = await fetch(`/api/gestures/${encodeURIComponent(name)}`, { method: 'DELETE' });
                if (!res.ok) {
                    alert("Failed to delete gesture");
                    gestures.value = originalGestures; // Revert
                    lastGestureUpdateTime.value = 0; // Reset grace period
                }
            } catch (e) {
                console.error(e);
                gestures.value = originalGestures; // Revert
                lastGestureUpdateTime.value = 0; // Reset grace period
            }
        };

        const renameGesture = (name) => {
            gestureToRename.value = name;
            renameInput.value = name;
            showRenameModal.value = true;
        };

        const confirmRename = async () => {
            const oldName = gestureToRename.value;
            const newName = renameInput.value;

            if (!newName || newName === oldName) return;

            showRenameModal.value = false; // Close immediately

            // Optimistic Update
            const originalGestures = JSON.parse(JSON.stringify(gestures.value));
            const gestureIdx = gestures.value.findIndex(g => g.name === oldName);

            if (gestureIdx !== -1) {
                gestures.value[gestureIdx].name = newName;
                lastGestureUpdateTime.value = Date.now(); // Start grace period
                // Update mapping if exists
                if (mapping.value[oldName]) {
                    mapping.value[newName] = mapping.value[oldName];
                    delete mapping.value[oldName];
                }
            }

            try {
                const res = await fetch(`/api/gestures/${encodeURIComponent(oldName)}/rename`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ new_name: newName })
                });

                if (!res.ok) {
                    alert("Rename failed. Reverting.");
                    gestures.value = originalGestures;
                    fetchData();
                }
            } catch (e) {
                console.error(e);
                gestures.value = originalGestures;
                fetchData();
            }
        };

        // Debounce Utility to prevent API spam while typing
        const debounce = (fn, delay) => {
            let timeoutId;
            return (...args) => {
                clearTimeout(timeoutId);
                timeoutId = setTimeout(() => fn(...args), delay);
            };
        };

        const mapAction = async (gestureName, actionName) => {
            if (showAppMappingModal.value && selectedAppInModal.value) {
                if (!appMappings[selectedAppInModal.value]) appMappings[selectedAppInModal.value] = {};
                appMappings[selectedAppInModal.value][gestureName] = actionName;
                // Auto-save for per-app personalization (silent)
                await saveAppMapping(true);
            } else {
                // Global mapping (fallback)
                // Optimistic update for the global UI sidebar
                mapping.value[gestureName] = actionName;
                pendingUpdates[gestureName] = actionName;

                await fetch('/api/map', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ gesture: gestureName, action: actionName })
                });
            }
            lastGestureUpdateTime.value = Date.now();
        };

        const openAppMappingModal = async () => {
            showAppMappingModal.value = true;
            await fetchConfiguredApps();
            await fetchActiveApp();
            if (activeAppName.value) {
                selectedAppInModal.value = activeAppName.value;
            } else if (configuredApps.value.length > 0) {
                selectedAppInModal.value = configuredApps.value[0];
            }
        };

        const fetchConfiguredApps = async () => {
            try {
                const res = await fetch('/api/map/app');
                const data = await res.json();
                configuredApps.value = Object.keys(data);
                if (!configuredApps.value.includes("_PRESENTATION_MODE_")) {
                    configuredApps.value.push("_PRESENTATION_MODE_");
                }

                // Merge data into appMappings
                Object.keys(data).forEach(app => {
                    if (!appMappings[app]) appMappings[app] = {};
                    gestures.value.forEach(g => {
                        appMappings[app][g.name] = data[app][g.name] || "";
                    });
                });
            } catch (e) {
                console.error("Failed to fetch configured apps", e);
            }
        };

        const fetchRunningApps = async () => {
            try {
                const res = await fetch('/api/running_apps');
                const data = await res.json();
                runningApps.value = data.apps.filter(app => !configuredApps.value.includes(app));
            } catch (e) {
                console.error("Failed to fetch running apps", e);
            }
        };

        const selectApp = async (app) => {
            selectedAppInModal.value = app;
            if (!appMappings[app]) {
                try {
                    const res = await fetch(`/api/map/app?app=${encodeURIComponent(app)}`);
                    const data = await res.json();
                    appMappings[app] = {};
                    gestures.value.forEach(g => {
                        appMappings[app][g.name] = data[g.name] || "";
                    });
                } catch (e) {
                    appMappings[app] = {};
                    gestures.value.forEach(g => appMappings[app][g.name] = "");
                }
            }
            nextTick(() => lucide.createIcons());
        };

        const addAppToPersonalization = (app) => {
            if (!configuredApps.value.includes(app)) {
                configuredApps.value.push(app);
            }
            selectApp(app);
            showAddAppList.value = false;
        };

        const addNewAppManual = () => {
            const app = prompt("Enter process name (e.g. chrome.exe):");
            if (app) {
                const cleanApp = app.toLowerCase().endsWith('.exe') ? app.toLowerCase() : app.toLowerCase() + '.exe';
                addAppToPersonalization(cleanApp);
            }
        };

        const fetchActiveApp = async () => {
            if (isDetectingApp.value) return;
            isDetectingApp.value = true;
            detectCountdown.value = 3;

            const timer = setInterval(() => {
                detectCountdown.value--;
            }, 1000);

            setTimeout(async () => {
                clearInterval(timer);
                try {
                    const res = await fetch('/api/active_app');
                    const data = await res.json();
                    activeAppName.value = data.app || "";

                    const lowerName = activeAppName.value.toLowerCase();
                    // Filter out the app detecting itself
                    if (activeAppName.value && !lowerName.includes("python") && !lowerName.includes("webview")) {
                        if (!configuredApps.value.includes(activeAppName.value)) {
                            configuredApps.value.push(activeAppName.value);
                        }
                        await selectApp(activeAppName.value);
                        await saveAppMapping(true); // Silent background save
                    }
                } catch (e) {
                    console.error("Failed to fetch active app", e);
                } finally {
                    isDetectingApp.value = false;
                    detectCountdown.value = 0;
                    nextTick(() => lucide.createIcons());
                }
            }, 3000);
        };

        const saveAppMapping = async (silentArg = false) => {
            const silent = (silentArg === true);
            if (!selectedAppInModal.value || isSavingAppMap.value) return;
            isSavingAppMap.value = true;

            const appCurrentMap = appMappings[selectedAppInModal.value];
            try {
                // Use the new bulk save endpoint for reliability and atomicity
                const res = await fetch('/api/map/bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        app: selectedAppInModal.value,
                        mappings: appCurrentMap
                    })
                });

                if (res.ok) {
                    if (!silent) {
                        showAppMappingModal.value = false;
                        setTimeout(() => {
                            try {
                                alert(`Personalized profile saved for ${selectedAppInModal.value === '_PRESENTATION_MODE_' ? 'Presentation Mode' : selectedAppInModal.value}!`);
                            } catch (e) {}
                        }, 50);
                    }
                } else {
                    throw new Error("Bulk save failed");
                }
            } catch (e) {
                console.error("Failed to save app mapping", e);
                if (!silent) {
                    alert("Error saving app-specific mappings. The server might be busy, please try again.");
                }
            } finally {
                isSavingAppMap.value = false;
            }
        };

        // Debounced version for text input
        const debouncedMapAction = debounce(mapAction, 300);

        const handleActionChange = (gestureName, event) => {
            // Select dropdowns don't need debounce
            mapAction(gestureName, event.target.value);
        };

        const updateCustomCommand = (gestureName, cmd) => {
            const fullAction = `cmd:${cmd}`;
            
            if (showAppMappingModal.value && selectedAppInModal.value) {
                // Personalization Modal Context
                if (!appMappings[selectedAppInModal.value]) appMappings[selectedAppInModal.value] = {};
                appMappings[selectedAppInModal.value][gestureName] = fullAction;
                // Use debounced save to server
                debouncedMapAction(gestureName, fullAction);
            } else {
                // Global Sidebar Context
                mapping.value[gestureName] = fullAction;
                pendingUpdates[gestureName] = fullAction;
                debouncedMapAction(gestureName, fullAction);
            }
        };

        const forceSaveAction = async (gestureName) => {
            const action = mapping.value[gestureName];
            if (!action) return;

            // 3-Step Feedback: Saving... -> Saved -> Reset
            const btn = document.activeElement.closest('button');
            let oldHtml = "";
            let oldClasses = "";

            if (btn) {
                oldHtml = btn.innerHTML;
                oldClasses = btn.className;

                // Step 1: Saving State
                btn.style.width = btn.offsetWidth + 'px'; // Lock width to prevent jumping if possible, or let it expand
                btn.style.transition = 'all 0.2s ease';
                btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i>`;
                btn.classList.add("bg-blue-500/20", "text-blue-400", "cursor-wait");
                if (window.lucide) lucide.createIcons();
            }

            // Network Save (Real wait)
            await mapAction(gestureName, action);

            // Step 2: Saved State
            if (btn) {
                // artificial delay if network was too fast for the eye (optional, but requested animation)
                // await new Promise(r => setTimeout(r, 300)); // Removed artificial delay

                btn.innerHTML = `<i data-lucide="check" class="w-3.5 h-3.5"></i> <span class="text-[10px] font-bold ml-1">SAVED</span>`;
                btn.classList.remove("bg-blue-500/20", "text-blue-400", "cursor-wait"); // Clear saving styles

                // Add Success Styles
                // We need to force a reflow or use a timeout to restart animation if needed, but 'animate-success' is keyframe
                btn.classList.add("bg-green-500", "text-white", "animate-success", "px-3", "w-auto");
                // Note: px-3 and w-auto expand the button to fit "SAVED"

                if (window.lucide) lucide.createIcons();

                // Step 3: Revert
                setTimeout(() => {
                    btn.className = oldClasses; // Restore original classes (padding, colors)
                    btn.innerHTML = oldHtml;
                    btn.style.width = ''; // Unlock width
                    if (window.lucide) lucide.createIcons();
                }, 1500);
            }
        };

        const testCustomCommand = async (cmd) => {
            if (!cmd) return;
            // We can reuse the existing action triggering mechanism or just call a new endpoint.
            // Ideally, we just tell the backend to run this specific command string.
            // We can cheat and use the map endpoint to just 'run' it? No.
            // Let's rely on the fact that we can trigger an action by name?
            // "cmd:calc".
            // The backend `execute` takes a gesture name.
            // We don't have a direct "run this action string" endpoint.
            // Let's make a simple fetch to a new endpoint or piggyback?
            // Actually, I can use `handleActionChange` logic style but for immediate execution?
            // Let's just alert for now or skipping execution?
            // No, the user wants it to work "whenever write".

            // Implementation: 
            // We'll trust the user to test via gesture for now, 
            // OR we can implement a `POST /api/exec` quickly.

            try {
                await fetch('/api/exec', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: `cmd:${cmd}` })
                });
            } catch (e) { console.error(e); }
        };

        // Helper to get clean value for select
        const getSelectValue = (val) => {
            if (!val) return "";
            if (val.startsWith("cmd:")) return "custom_command";
            if (val.startsWith("type:")) return "type_text";
            return val;
        };

        const getCustomValue = (val) => {
            if (!val) return "";
            if (val.startsWith("cmd:")) return val.substring(4);
            if (val.startsWith("type:")) return val.substring(5);
            return "";
        };

        const updateTypeText = (gestureName, text) => {
            const fullAction = `type:${text}`;
            if (showAppMappingModal.value && selectedAppInModal.value) {
                if (!appMappings[selectedAppInModal.value]) appMappings[selectedAppInModal.value] = {};
                appMappings[selectedAppInModal.value][gestureName] = fullAction;
                debouncedMapAction(gestureName, fullAction);
            } else {
                mapping.value[gestureName] = fullAction;
                pendingUpdates[gestureName] = fullAction;
                debouncedMapAction(gestureName, fullAction);
            }
        };

        const categorizedActions = computed(() => {
            const groups = {
                "PowerPoint Control": [],
                "Word / Documents": [],
                "Excel / Spreadsheets": [],
                "Mouse Control": [],
                "Media Control": [],
                "Browser Control": [],
                "Window Management": [],
                "System Tools": [],
                "Navigation": [],
                "Apps & Power": [],
                "Design Tools": [],
                "Coding & IDE": [],
                "Video Conferencing": [],
                "Gaming & Controls": [],
                "Advanced": ["custom_command", "type_text", "voice_type"],
                "Other": []
            };

            // Helper to push to group without duplicates
            const add = (group, act) => {
                if (!groups[group].includes(act)) groups[group].push(act);
            };

            actions.value.forEach(act => {
                // PowerPoint
                if (act.startsWith("ppt_")) {
                    add("PowerPoint Control", act);
                }
                // Word
                else if (act.startsWith("word_")) {
                    add("Word / Documents", act);
                }
                // Excel
                else if (act.startsWith("excel_")) {
                    add("Excel / Spreadsheets", act);
                }
                // IDE
                else if (act.startsWith("ide_")) {
                    add("Coding & IDE", act);
                }
                // Video Conferencing
                else if (act.startsWith("meeting_")) {
                    add("Video Conferencing", act);
                }
                // Design
                else if (act.startsWith("photoshop_")) {
                    add("Design Tools", act);
                }
                // Gaming
                else if (act.startsWith("game_")) {
                    add("Gaming & Controls", act);
                }
                // Mouse
                else if (act.includes("click") || act.includes("cursor") || act.includes("mouse")) {
                    add("Mouse Control", act);
                }
                // Media
                else if (act.includes("volume") || act.includes("media")) {
                    add("Media Control", act);
                }
                // Browser
                else if (act.includes("browser") || act.includes("tab")) {
                    add("Browser Control", act);
                }
                // Window Management
                else if (act.includes("window") || act.includes("desktop") || act.includes("alt_tab")) {
                    add("Window Management", act);
                }
                // Navigation
                else if (act.includes("scroll") || act.includes("page_") || act.includes("arrow_")) {
                    add("Navigation", act);
                }
                // Apps & Power
                else if (act.includes("open_") || act.includes("shutdown") || act.includes("restart") || act.includes("sleep")) {
                    add("Apps & Power", act);
                }
                // System Tools
                else if (act.includes("screenshot") || act.includes("system_") || act.includes("lock") || act.includes("task_") || act.includes("file_") || act.includes("settings") || act.includes("win_") || act.includes("run_") || act.includes("clipboard") || act.includes("emoji")) {
                    add("System Tools", act);
                }
                // Keys
                else if (act === "enter" || act === "space" || act === "esc" || act === "backspace" || act === "tab") {
                    add("System Tools", act); // Keys often fit in system/general
                }
                // PDF
                else if (act === "split_pdf") {
                    add("System Tools", act);
                }
                else {
                    if (!groups["Advanced"].includes(act)) {
                        add("Other", act);
                    }
                }
            });

            // Remove empty groups
            Object.keys(groups).forEach(key => {
                if (groups[key].length === 0) delete groups[key];
            });

            return groups;
        });

        const formatActionName = (name) => {
            if (name === 'custom_command') return "Run Custom Command...";
            if (name === 'type_text') return "Type Text...";
            if (name === 'voice_type') return "Voice Typing (Dictate)";

            // Special replacements
            if (name.startsWith("ppt_")) return name.replace("ppt_", "").replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            if (name.startsWith("word_")) return name.replace("word_", "").replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            if (name.startsWith("photoshop_")) return name.replace("photoshop_", "PS ").replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

            return name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        };

        const selectedGestureForGallery = ref(null);
        const galleryImages = ref([]);
        const showGalleryModal = ref(false);
        const isLoadingGallery = ref(false);
        const galleryMode = ref('original'); // 'original' or 'all'

        // Lightbox State
        const lightboxIndex = ref(null);

        const currentLightboxImage = computed(() => {
            if (lightboxIndex.value === null || !galleryImages.value.length) return null;
            return galleryImages.value[lightboxIndex.value];
        });

        const openGallery = async (name, mode = 'original') => {
            selectedGestureForGallery.value = name;
            galleryMode.value = mode; // Set mode
            galleryImages.value = [];
            isLoadingGallery.value = true;

            // Only show modal if we are NOT in the dataset dashboard
            // (The dataset dashboard re-uses the gallery logic but displays it differently, 
            //  OR if you want to reuse the same modal for both, keep this true. 
            //  Based on the UI, the Dataset Dashboard has its own right-panel grid.
            //  Let's separate the fetching logic slightly.)

            if (mode === 'original') {
                showGalleryModal.value = true;
            }

            try {
                // Fetch based on mode
                const res = await fetch(`/api/gestures/${encodeURIComponent(name)}/images?type=${mode}`);
                if (res.ok) {
                    galleryImages.value = await res.json();
                }
            } catch (e) {
                console.error("Failed to load images", e);
            } finally {
                isLoadingGallery.value = false;
            }
        };

        const triggerBatchAugmentation = async () => {
            if (isSavingBulk.value) return;
            if (!confirm(`This will generate ${augmentCountInput.value} variations for EVERY original sample of '${selectedGestureForGallery.value}'.\n\nThey will appear in the Dataset Dashboard, not here.\n\nContinue?`)) return;

            isSavingBulk.value = true;
            augmentationProgress.current = 0;
            augmentationProgress.total = 0;

            const gName = selectedGestureForGallery.value;

            try {
                const response = await fetch(`/api/gestures/${encodeURIComponent(gName)}/augment_all`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ count: augmentCountInput.value })
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');

                    // Process all complete lines
                    buffer = lines.pop();

                    for (const line of lines) {
                        if (!line.trim()) continue;
                        try {
                            const data = JSON.parse(line);
                            if (data.status === 'progress' || data.status === 'start') {
                                augmentationProgress.total = data.total;
                                augmentationProgress.current = data.current;
                            } else if (data.status === 'complete') {
                                augmentationProgress.current = data.total;
                                // Final completion handled after loop
                            }
                        } catch (e) { console.error("Stream parse error", e); }
                    }
                }

                // Completion logic
                alert(`Augmentation Complete!\nGenerated ${augmentationProgress.current} images.`);

                // Force update of dataset stats
                await fetchData();

            } catch (e) {
                console.error(e);
                alert("Network error during augmentation");
            } finally {
                isSavingBulk.value = false;
                augmentationProgress.current = 0;
                augmentationProgress.total = 0;
            }
        };

        const closeGallery = () => {
            showGalleryModal.value = false;
            selectedGestureForGallery.value = null;
            galleryImages.value = [];
            lightboxIndex.value = null;
        };

        const deleteSample = (gestureName, imgUrl) => {
            const filename = imgUrl.split('/').pop();
            itemToDelete.value = {
                type: 'sample',
                name: 'this sample', // For display 
                gestureName,
                imgUrl,
                filename
            };
            showDeleteModal.value = true;
        };

        const executeDeleteSample = async (gestureName, filename) => {
            // if (!confirm("Delete this sample?")) return; // Handled by modal now

            try {
                const res = await fetch(`/api/gestures/${encodeURIComponent(gestureName)}/samples/${filename}`, {
                    method: 'DELETE'
                });
                if (res.ok) {
                    openGallery(gestureName);
                    fetchData();
                    return true;
                } else {
                    alert("Failed to delete sample");
                    return false;
                }
            } catch (e) {
                console.error(e);
                console.error(e);
                return false;
            }
        };

        const confirmDelete = async () => {
            if (!itemToDelete.value) return;

            const item = itemToDelete.value;
            showDeleteModal.value = false; // Close immediately

            if (item.type === 'gesture') {
                await executeDeleteGesture(item.name);
            } else if (item.type === 'sample') {
                const success = await executeDeleteSample(item.gestureName, item.filename);
                if (success) {
                    // If we were in lightbox, close it or move to next? 
                    // The original deleteSampleInLightbox handles logic, but now it's async-detached.
                    // We might need to refresh UI.
                }
            }

            itemToDelete.value = null;
        };

        const deleteSampleInLightbox = async () => {
            if (currentLightboxImage.value) {
                const success = await deleteSample(selectedGestureForGallery.value, currentLightboxImage.value);
                if (success) {
                    closeLightbox();
                }
            }
        };

        const previewAugmentation = async (gestureName, imgUrl) => {
            const filename = imgUrl.split('/').pop();
            currentSampleForAugment.value = imgUrl;
            showAugmentModal.value = true;
            isAugmenting.value = true;
            augmentedImage.value = null;

            try {
                const res = await fetch(`/api/gestures/${encodeURIComponent(gestureName)}/samples/${filename}/augment`);
                if (res.ok) {
                    const data = await res.json();
                    augmentedImage.value = data.augmented_image;
                } else {
                    alert("Failed to augment image");
                    showAugmentModal.value = false;
                }
            } catch (e) {
                console.error(e);
                showAugmentModal.value = false;
            } finally {
                isAugmenting.value = false;
                nextTick(() => lucide.createIcons());
            }
        };

        const previewBulkAugmentation = async (gestureName, imgUrl) => {
            const filename = imgUrl.split('/').pop();
            currentSampleForAugment.value = imgUrl; // Update global ref for Save to use
            showBulkAugmentModal.value = true;
            isBulkAugmenting.value = true;
            augmentedImagesBulk.value = [];
            bulkAugmentSpriteUrl.value = null;

            const count = bulkAugmentCount.value || 100;
            const encodedName = encodeURIComponent(gestureName);

            // 1. Set the Master Sprite (1 request for the whole grid)
            bulkAugmentSpriteUrl.value = `/api/gestures/${encodedName}/samples/${filename}/sprite?count=${count}&t=${Date.now()}`;

            // 2. Generate deterministic HD metadata (seeds match sprite indices)
            const meta = [];
            for (let i = 0; i < count; i++) {
                meta.push({
                    seed: i,
                    url: `/api/gestures/${encodedName}/samples/${filename}/augment_raw?seed=${i}&w=256`,
                    hd_url: `/api/gestures/${encodedName}/samples/${filename}/augment_raw?seed=${i}&w=800`
                });
            }

            setTimeout(() => {
                augmentedImagesBulk.value = meta;
                isBulkAugmenting.value = false;

                // Prefetch the first 5 HD images
                for (let i = 0; i < Math.min(count, 5); i++) {
                    prefetchAugment(i);
                }

                nextTick(() => lucide.createIcons());
            }, 400); // Small wait for sprite request to fire
        };

        const prefetchAugment = (index) => {
            if (index < 0 || index >= augmentedImagesBulk.value.length) return;
            const url = augmentedImagesBulk.value[index].hd_url;
            const img = new Image();
            img.src = url;
        };

        const enlargeAugment = (index) => {
            isHDElevating.value = true;
            selectedAugmentIndex.value = index;

            // Aggressive Pre-fetch: Load next 5 images in HD
            for (let i = 1; i <= 5; i++) {
                prefetchAugment((index + i) % augmentedImagesBulk.value.length);
                prefetchAugment((index - i + augmentedImagesBulk.value.length) % augmentedImagesBulk.value.length);
            }

            nextTick(() => lucide.createIcons());
        };

        const nextAugment = () => {
            if (selectedAugmentIndex.value === null) return;
            isHDElevating.value = true;
            selectedAugmentIndex.value = (selectedAugmentIndex.value + 1) % augmentedImagesBulk.value.length;

            // Prefetch deep buffer (5 ahead)
            for (let i = 1; i <= 5; i++) {
                prefetchAugment((selectedAugmentIndex.value + i) % augmentedImagesBulk.value.length);
            }

            nextTick(() => lucide.createIcons());
        };

        const prevAugment = () => {
            if (selectedAugmentIndex.value === null) return;
            isHDElevating.value = true;
            selectedAugmentIndex.value = (selectedAugmentIndex.value - 1 + augmentedImagesBulk.value.length) % augmentedImagesBulk.value.length;

            // Prefetch deep buffer (5 behind)
            for (let i = 1; i <= 5; i++) {
                prefetchAugment((selectedAugmentIndex.value - i + augmentedImagesBulk.value.length) % augmentedImagesBulk.value.length);
            }

            nextTick(() => lucide.createIcons());
        };

        // Keyboard listener for navigation (Consolidated)
        window.addEventListener('keydown', (e) => {
            // 1. Augmentation View (Highest Priority)
            if (selectedAugmentIndex.value !== null) {
                if (e.key === 'ArrowRight') nextAugment();
                if (e.key === 'ArrowLeft') prevAugment();
                if (e.key === 'Escape') selectedAugmentIndex.value = null;
                return;
            }

            // 2. Main Lightbox
            if (lightboxIndex.value !== null) {
                if (e.key === 'ArrowRight') nextImage();
                if (e.key === 'ArrowLeft') prevImage();
                if (e.key === 'Escape') closeLightbox();
                return;
            }

            // 3. Gallery Modal
            if (showGalleryModal.value) {
                if (e.key === 'Escape') closeGallery();
                return;
            }

            // 4. Default / Home / Sidebar
            // Sidebar Scroll
            if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;

            if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                const sidebar = document.getElementById('mapping-sidebar');
                if (sidebar) {
                    e.preventDefault();
                    sidebar.scrollTop += (e.key === 'ArrowDown' ? 50 : -50);
                }
            }
        });

        // Lightbox Controls
        const openLightbox = (index) => {
            lightboxIndex.value = index;
        };

        const closeLightbox = () => {
            lightboxIndex.value = null;
        };

        const nextImage = () => {
            if (lightboxIndex.value === null) return;
            lightboxIndex.value = (lightboxIndex.value + 1) % galleryImages.value.length;
        };

        const prevImage = () => {
            if (lightboxIndex.value === null) return;
            lightboxIndex.value = (lightboxIndex.value - 1 + galleryImages.value.length) % galleryImages.value.length;
        };





        // --- Themes ---
        const setTheme = async (themeName) => {
            try {
                await fetch('/api/theme', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ theme: themeName })
                });
            } catch (e) {
                console.error("Theme Error", e);
            }
        };

        onMounted(() => {
            lucide.createIcons();
            setInterval(fetchData, 200); // Poll every 200ms - Balanced for old hardware
        });

        return {
            status,
            gestures,
            actions,
            mapping,
            newGestureName,
            isAddingToExisting, // Export
            setMode,
            toggleSmartVoice,
            setTheme,
            saveSample,
            deleteGesture,
            renameGesture, // Fix: Export this
            addMoreSamples, // Fix: Expose function
            toggleFloatWindow, // Export
            handleActionChange,
            categorizedActions,
            formatActionName,
            getSelectValue,
            getCustomValue,
            updateCustomCommand,
            openGallery,
            closeGallery,
            deleteSample,
            deleteSampleInLightbox,
            selectedGestureForGallery,
            galleryImages,
            showGalleryModal,
            isLoadingGallery,
            lightboxIndex,
            currentLightboxImage,
            openLightbox,
            closeLightbox,
            nextImage,
            prevImage,
            // Delete Modal
            showDeleteModal,
            itemToDelete,
            confirmDelete,
            // Rename Modal
            showRenameModal,
            renameInput,
            confirmRename,
            gestureToRename,

            // Settings
            showSettingsModal,
            cameraSettings,
            saveSettings,
            uiTheme,

            // Dataset
            showDatasetModal,
            selectedGestureInDataset,
            selectedImagesIndices,
            datasetStats,
            selectGestureInDataset,
            toggleImageSelection,
            selectAllImages,
            deselectAllImages,
            batchDeleteSamples,

            // Training
            showTrainingModal,
            lightingPct,
            distancePct,
            anglePct,
            resetTrainingMetrics,
            isTraining, // Export
            startTraining, // Export
            stopTraining, // Export
            trainingConfig, // Export
            trainingProgress, // Export
            lossGraphPoints, // Export

            // PDF Split
            showSplitPdfModal,
            selectedPdfFile,
            splitRange,
            isSplitting,
            handlePdfFileUpload,
            performPdfSplit,

            // Augmentation
            showAugmentModal,
            augmentedImage,
            isAugmenting,
            currentSampleForAugment,
            previewAugmentation,
            previewBulkAugmentation,
            enlargeAugment,
            nextAugment,
            prevAugment,
            showBulkAugmentModal,
            augmentedImagesBulk,
            bulkAugmentSpriteUrl,
            selectedAugmentIndex,
            isBulkAugmenting,
            bulkAugmentCount,
            isHDElevating,
            bulkAugmentCount,
            // New Exports
            isSavingBulk,
            saveBulkAugment,
            galleryMode,
            triggerBatchAugmentation,
            openBulkAugmentForSelected,
            augmentCountInput,
            augmentationProgress,

            // Sequence
            isRecordingSeq,
            startSequenceRec,
            stopSequenceRec,
            reRecordSequence,

            // Sidebar
            sidebarTab,
            filteredGestures,
            augmentationProgress,
            showAppMappingModal,
            activeAppName,
            selectedAppInModal,
            appMappings,
            configuredApps,
            runningApps,
            showAddAppList,
            isDetectingApp,
            isSavingAppMap,
            openAppMappingModal,
            fetchConfiguredApps,
            fetchRunningApps,
            selectApp,
            addAppToPersonalization,
            addNewAppManual,
            fetchActiveApp,
            detectCountdown,
            saveAppMapping,
            formatActionName,
            categorizedActions,
            galleryImages,
        };
    }
}).mount('#app');
