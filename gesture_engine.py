import numpy as np
import json
import os
import logging
import shutil
from config import Config

logger = logging.getLogger(__name__)

class GestureEngine:
    def __init__(self, gestures_file=None):
        self.gestures_file = gestures_file or Config.GESTURES_FILE
        self.gestures = self.load_gestures()
        self.sequences = self.load_sequences()
        # Threshold for matching a gesture
        self.match_threshold = 0.85
        self.dtw_threshold = 0.5 # Strictness for dynamic gestures
        self.smoothing_window = 5
        self.prediction_history = []
        
        # --- ULTIMATE UPGRADE: Kalman Predictive Tracking ---
        # 63 states: (21 landmarks * 3 coordinates)
        # Reduced measurement noise (r=0.01) and increased process noise (q=0.05) to eliminate latency and lag!
        self.kalman = KalmanFilter63(q=0.05, r=0.01) 
        
        # --- ULTIMATE UPGRADE: Neural Ensemble ---
        self.use_neural = False # Toggle via API
        self.neural_model = None # Placeholder for loaded CNN/RNN

    def load_sequences(self):
        seq_file = Config.SEQUENCES_FILE if hasattr(Config, 'SEQUENCES_FILE') else "sequences.json"
        if os.path.exists(seq_file):
            try:
                with open(seq_file, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} sequences: {list(data.keys())}")
                    return data
            except Exception as e:
                logger.error(f"Failed to load sequences: {e}")
        return {}

    def save_sequence(self, name: str, sequence):
        seq_file = Config.SEQUENCES_FILE if hasattr(Config, 'SEQUENCES_FILE') else "sequences.json"
        try:
            # Ensure directory exists if path contains folders
            if os.path.dirname(seq_file):
                os.makedirs(os.path.dirname(seq_file), exist_ok=True)

            # Create the per-sequence folder too (for user consistency)
            seq_dir = os.path.join("sequences", name)
            os.makedirs(seq_dir, exist_ok=True)
            
            # Normalize entire sequence
            normalized_seq = []
            for frame in sequence:
                norm = self._normalize_landmarks(frame)
                # Convert to list if it's numpy array
                if isinstance(norm, np.ndarray):
                    norm = norm.tolist()
                normalized_seq.append(norm)
            
            self.sequences[name] = normalized_seq
            
            with open(seq_file, 'w') as f:
                json.dump(self.sequences, f, indent=4)
            
            logger.info(f"Sequence '{name}' saved. Frames: {len(sequence)}")
            return True
        except Exception as e:
            logger.error(f"Failed to save sequence '{name}': {e}")
            import traceback
            traceback.print_exc()
            return False

    def find_dynamic_gesture(self, history_buffer):
        """
        Compares the history buffer (sequence of frames) against stored sequences using DTW.
        """
        if not self.sequences or len(history_buffer) < 10:
            return None

        # Normalize input buffer
        input_seq = np.array([self._normalize_landmarks(frame) for frame in history_buffer])
        
        best_match = None
        min_dist = float('inf')

        for name, target_seq in self.sequences.items():
            target_seq_np = np.array(target_seq)
            
            # Optimization: Skip if length difference is too massive
            if abs(len(input_seq) - len(target_seq_np)) > 20: 
                continue

            dist = self._dtw_distance(input_seq, target_seq_np)
            
            # Normalize distance by length to compare sequences of different lengths
            norm_dist = dist / (len(input_seq) + len(target_seq_np))
            
            if norm_dist < min_dist:
                min_dist = norm_dist
                best_match = name

        if min_dist < self.dtw_threshold:
            logger.info(f"Dynamic Match: {best_match} (Dist: {min_dist:.4f})")
            return best_match
            
        return None

    def _dtw_distance(self, s1, s2):
        """
        Compute Dynamic Time Warping (DTW) distance with high-speed vectorized numpy.
        """
        n, m = len(s1), len(s2)
        
        # Ultra-fast vectorized distance matrix calculation (NO python loops!)
        # s1 is (N, D), s2 is (M, D) -> diff is (N, M, D) -> norm is (N, M)
        cost_matrix = np.linalg.norm(s1[:, None, :] - s2[None, :, :], axis=2)
        
        dtw_matrix = np.full((n+1, m+1), float('inf'))
        dtw_matrix[0, 0] = 0
        
        for i in range(1, n+1):
            for j in range(1, m+1):
                cost = cost_matrix[i-1, j-1]
                # Use python built-in min for scalars to avoid slow numpy overhead
                dtw_matrix[i, j] = cost + min(dtw_matrix[i-1, j], dtw_matrix[i, j-1], dtw_matrix[i-1, j-1])
                
        return dtw_matrix[n, m]

    def load_gestures(self):
        if os.path.exists(self.gestures_file):
            try:
                with open(self.gestures_file, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} gestures: {list(data.keys())}")
                    return data
            except Exception as e:
                logger.error(f"Failed to load gestures: {e}")
        else:
            logger.warning(f"Gestures file not found at {self.gestures_file}. Starting fresh.")
        return {}

    def save_gesture(self, name: str, landmarks):
        """
        Saves a gesture sample. Appends to the list of samples for 'name'.
        """
        try:
            normalized = self._normalize_landmarks(landmarks)
            
            # Ensure list structure
            if name not in self.gestures:
                self.gestures[name] = []
            
            # Append new sample (convert np array to list for JSON serialization)
            self.gestures[name].append(normalized.tolist() if isinstance(normalized, np.ndarray) else normalized)
            
            os.makedirs(os.path.dirname(self.gestures_file), exist_ok=True)
            with open(self.gestures_file, 'w') as f:
                json.dump(self.gestures, f, indent=4)
            
            logger.info(f"Gesture '{name}' sample saved. Total samples: {len(self.gestures[name])}")
            return True
        except Exception as e:
            logger.error(f"Failed to save gesture '{name}': {e}")
            return False
            
    def delete_sample(self, name: str, index: int):
        """
        Deletes a specific sample at the given index.
        """
        if name in self.gestures:
            try:
                samples = self.gestures[name]
                if 0 <= index < len(samples):
                    samples.pop(index)
                    
                    # If empty, keep the key? Or delete? 
                    # Let's keep the key so the gesture still "exists" even if empty, until explicitly deleted.
                    
                    with open(self.gestures_file, 'w') as f:
                        json.dump(self.gestures, f, indent=4)
                    return True
            except Exception as e:
                logger.error(f"Error deleting sample: {e}")
        return False



    def rename_gesture(self, old_name: str, new_name: str):
        """
        Renames a gesture (static or dynamic) from old_name to new_name.
        """
        renamed = False
        
        # 1. Handle Static Gestures
        if old_name in self.gestures:
             if new_name not in self.gestures:
                try:
                    self.gestures[new_name] = self.gestures.pop(old_name)
                    with open(self.gestures_file, 'w') as f:
                        json.dump(self.gestures, f, indent=4)
                    
                    old_dir = os.path.join("samples", old_name)
                    new_dir = os.path.join("samples", new_name)
                    if os.path.exists(old_dir) and not os.path.exists(new_dir):
                        os.rename(old_dir, new_dir)
                    renamed = True
                except Exception as e:
                    logger.error(f"Failed to rename static gesture: {e}")

        # 2. Handle Dynamic Sequences
        if old_name in self.sequences:
             if new_name not in self.sequences:
                try:
                    self.sequences[new_name] = self.sequences.pop(old_name)
                    seq_file = Config.SEQUENCES_FILE if hasattr(Config, 'SEQUENCES_FILE') else "sequences.json"
                    with open(seq_file, 'w') as f:
                        json.dump(self.sequences, f, indent=4)
                        
                    # Rename Sequence Folder (if we start making one)
                    old_seq_dir = os.path.join("sequences", old_name)
                    new_seq_dir = os.path.join("sequences", new_name)
                    
                    # Create parent dir if missing
                    os.makedirs("sequences", exist_ok=True)
                    
                    if os.path.exists(old_seq_dir) and not os.path.exists(new_seq_dir):
                         os.rename(old_seq_dir, new_seq_dir)
                    elif not os.path.exists(new_seq_dir):
                         # If old didn't exist (legacy), just create new one
                         os.makedirs(new_seq_dir, exist_ok=True)
                         
                    renamed = True
                except Exception as e:
                    logger.error(f"Failed to rename sequence: {e}")

        return renamed

    def delete_gesture(self, name: str):
        """
        Deletes a gesture (static or dynamic) and its associated files.
        """
        deleted = False
        
        # 1. Static
        if name in self.gestures:
            try:
                del self.gestures[name]
                with open(self.gestures_file, 'w') as f:
                    json.dump(self.gestures, f, indent=4)
                
                sample_dir = os.path.join("samples", name)
                if os.path.exists(sample_dir):
                    shutil.rmtree(sample_dir)
                deleted = True
            except Exception as e:
                logger.error(f"Failed to delete static gesture {name}: {e}")

        # 2. Dynamic
        if name in self.sequences:
            try:
                del self.sequences[name]
                seq_file = Config.SEQUENCES_FILE if hasattr(Config, 'SEQUENCES_FILE') else "sequences.json"
                with open(seq_file, 'w') as f:
                    json.dump(self.sequences, f, indent=4)
                    
                seq_dir = os.path.join("sequences", name)
                if os.path.exists(seq_dir):
                    shutil.rmtree(seq_dir)
                deleted = True
            except Exception as e:
                logger.error(f"Failed to delete sequence {name}: {e}")
                
        return deleted

    def get_training_stats(self):
        """
        Calculates training metrics:
        1. Model Type: Geometric Vector Classifier (KNN-1)
        2. Loss: Average Intra-Cluster Variance (lower is better)
        3. Accuracy: Leave-One-Out Cross-Validation (LOOCV)
        """
        stats = {
            "model_type": "Geometric Vector Classifier (KNN)",
            "total_samples": 0,
            "accuracy": 0.0,
            "loss": 0.0,
            "breakdown": {}
        }

        # Flatten all samples for efficient LOOCV
        all_samples = []
        labels = []
        
        # 1. Calc Variance (Loss) per Gesture
        total_variance = 0
        gesture_count = 0
        
        for name, samples in self.gestures.items():
            if not samples: continue
            
            # Convert to numpy for math
            # Handle potential inconsistent list nesting from JSON
            clean_samples = []
            for s in samples:
                 if isinstance(s, list):
                     clean_samples.append(np.array(s))
                 else:
                     clean_samples.append(np.array(s)) # Already array?

            if not clean_samples: continue

            # Stack 
            data_stack = np.stack(clean_samples)
            
            # Variance (Mean squared distance from centroid)
            centroid = np.mean(data_stack, axis=0)
            distances = np.linalg.norm(data_stack - centroid, axis=1)
            variance = np.mean(distances ** 2)
            
            total_variance += variance
            gesture_count += 1
            
            # Add to global list for Accuracy check
            for s in clean_samples:
                all_samples.append(s)
                labels.append(name)
                
            stats["breakdown"][name] = {
                "samples": len(samples),
                "variance": float(variance)
            }

        stats["total_samples"] = len(all_samples)
        stats["loss"] = float(total_variance / gesture_count) if gesture_count > 0 else 0.0

        # 2. Calc Accuracy (LOOCV)
        # For each sample, treat it as "test" and others as "train"
        # Find nearest neighbor in "others". If label matches, Correct.
        
        if len(all_samples) < 2:
            stats["accuracy"] = 0.0 if not all_samples else 1.0 # Trivial
            return stats

        correct = 0
        total = len(all_samples)
        
        # Optimize: Compute full distance matrix once? Or simple loop for clarity.
        # Simple loop is fine for < 1000 samples.
        for i in range(total):
            test_sample = all_samples[i]
            true_label = labels[i]
            
            best_dist = float('inf')
            predicted_label = None
            
            for j in range(total):
                if i == j: continue # Skip self
                
                dist = np.linalg.norm(test_sample - all_samples[j])
                if dist < best_dist:
                    best_dist = dist
                    predicted_label = labels[j]
            
            if predicted_label == true_label:
                correct += 1
                
        stats["accuracy"] = (correct / total) * 100.0 if total > 0 else 0.0
        
        return stats

    def find_gesture(self, landmarks):
        """
        Compares input against all samples.
        Returns name if match is found and is not ambiguous.
        """
        if not self.gestures:
            return None

        current_feat = self._normalize_landmarks(landmarks)
        
        # Track top 2 matches for ambiguity check
        best_match = None
        min_dist = float('inf')
        
        second_best_dist = float('inf')
        second_best_match = None

        for name, samples in self.gestures.items():
            # Normalize samples list format
            if not isinstance(samples, list) or (len(samples) > 0 and not isinstance(samples[0], list)):
                if len(samples) > 0 and isinstance(samples[0], (int, float)):
                     samples = [samples]
            
            # Find closest sample for THIS gesture
            local_min = float('inf')
            for sample in samples:
                dist = self._calculate_distance(current_feat, sample)
                if dist < local_min:
                    local_min = dist
            
            # Now compare local_min to global bests
            if local_min < min_dist:
                # Update runner-up
                second_best_dist = min_dist
                second_best_match = best_match
                
                # New best
                min_dist = local_min
                best_match = name
            elif local_min < second_best_dist:
                second_best_dist = local_min
                second_best_match = name

        if min_dist < self.match_threshold:
            # Ambiguity Check
            ambiguity_margin = 0.10 
            
            if second_best_match and (second_best_dist - min_dist) < ambiguity_margin:
                logger.debug(f"Ambiguous: {best_match}({min_dist:.2f}) vs {second_best_match}({second_best_dist:.2f})")
                return None
                
            logger.debug(f"Matched: {best_match} | Dist: {min_dist:.3f}")
            return best_match
            
        return None

    def _normalize_landmarks(self, landmarks):
        """
        Converts 21 landmarks into a feature vector of angles.
        """
        # Convert to numpy array (21, 3)
        coords = []
        for lm in landmarks:
            if hasattr(lm, 'x'):
                coords.append([lm.x, lm.y, lm.z])
            elif isinstance(lm, dict) and 'x' in lm:
                coords.append([lm['x'], lm['y'], lm.get('z', 0.0)])
            else:
                coords.append(lm) # Fallback for list/array
        coords = np.array(coords)

        # Edges for angle calculation
        connections = [
            (0,1), (1,2), (2,3), (3,4),       # Thumb
            (0,5), (5,6), (6,7), (7,8),       # Index
            (0,9), (9,10), (10,11), (11,12),  # Middle
            (0,13), (13,14), (14,15), (15,16),# Ring
            (0,17), (17,18), (18,19), (19,20) # Pinky
        ]
        
        # --- INDUSTRIAL UPGRADE: Rotation & Tilt Compensation ---
        # 0: Wrist, 5: Index MCP, 17: Pinky MCP
        p0 = coords[0]
        p5 = coords[5]
        p17 = coords[17]
        
        # 1. Define Local Coordinate System (Hand Plane)
        v_x = p5 - p0
        v_x = v_x / (np.linalg.norm(v_x) + 1e-6)
        
        v_tmp = p17 - p0
        v_z = np.cross(v_x, v_tmp) # Normal vector to palm
        v_z = v_z / (np.linalg.norm(v_z) + 1e-6)
        
        v_y = np.cross(v_z, v_x) # Orthogonal y-axis
        
        # 2. Build Rotation Matrix
        R = np.stack([v_x, v_y, v_z]) 
        
        # 3. Transform all points to local "flat" system
        # Center at wrist (p0)
        local_coords = (coords - p0) @ R.T
        
        # 4. SCALE INVARIANT: Normalize by palm size
        palm_size = np.linalg.norm(p5 - p17) + 1e-6
        local_coords = local_coords / palm_size

        vectors = []
        for start, end in connections:
            v = local_coords[end] - local_coords[start]
            norm = np.linalg.norm(v)
            if norm == 0:
                v_norm = v
            else:
                v_norm = v / norm
            vectors.append(v_norm)
        
        angles = []
        
        # 1. Intra-finger angles (Curl)
        finger_indices = [
            [0,1,2,3], [4,5,6,7], [8,9,10,11], [12,13,14,15], [16,17,18,19] 
        ]
        
        for f_vecs in finger_indices:
            for i in range(len(f_vecs)-1):
                v1 = vectors[f_vecs[i]]
                v2 = vectors[f_vecs[i+1]]
                dot = np.dot(v1, v2)
                dot = np.clip(dot, -1.0, 1.0)
                angle = np.arccos(dot)
                angles.append(angle)
                
        # 2. Inter-finger spread
        bases = [0, 4, 8, 12, 16]
        for i in range(len(bases)-1):
            v1 = vectors[bases[i]]
            v2 = vectors[bases[i+1]]
            dot = np.dot(v1, v2)
            dot = np.clip(dot, -1.0, 1.0)
            angle = np.arccos(dot)
            angles.append(angle)

        return np.array(angles)

    def _calculate_distance(self, gesture1, gesture2):
        g1 = np.array(gesture1)
        g2 = np.array(gesture2)
        return np.linalg.norm(g1 - g2)

class KalmanFilter63:
    """
    Predictive smoothing for 21 hand landmarks (63 values).
    Used to eliminate jitter and predict future positions.
    """
    def __init__(self, q=0.01, r=0.1):
        self.q = q # Process noise
        self.r = r # Measurement noise
        self.p = np.ones(63) # Error covariance
        self.x = np.zeros(63) # Initial state
        self.initialized = False

    def update(self, measurement):
        if not isinstance(measurement, np.ndarray):
            measurement = np.array(measurement).flatten()
            
        if not self.initialized:
            self.x = measurement
            self.p = np.ones(63)
            self.initialized = True
            return measurement

        # Prediction phase
        # x = x (Constant position model)
        # p = p + q
        self.p = self.p + self.q

        # Update phase
        # k = p / (p + r)
        k = self.p / (self.p + self.r)
        
        # x = x + k * (z - x)
        self.x = self.x + k * (measurement - self.x)
        
        # p = (1 - k) * p
        self.p = (1 - k) * self.p
        
        return self.x

    def reset(self):
        self.initialized = False
