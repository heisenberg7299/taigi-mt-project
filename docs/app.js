// 台語翻譯候選答案 - 母語者驗證平台（靜態版，取代原本跑在本機Mac上的Flask版）。
// 不需要任何伺服器常駐：GitHub Pages 發布靜態檔案，Firebase Firestore 存回覆資料。
// 邏輯是把 taigi-mt-project/webapp/app.py 的行為原樣搬過來，資料模型改一下：
//   taigi_tokens/{name}          -> { token, createdAt }  同名字接回進度用
//   taigi_reviews/{token}        -> { name, currentBatch: [id...], batchCreatedAt }
//   taigi_reviews/{token}/items/{sentenceId} -> 個別回覆
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getFirestore, doc, getDoc, setDoc, collection, getDocs, serverTimestamp,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore.js";
import { firebaseConfig } from "./firebase-config.js";

// 這個專案沒開Firebase Anonymous Auth，測試者不用登入——taigi_reviews/taigi_tokens
// 這兩個collection直接開放讀寫（見 english-vocab-app/firestore.rules），
// 安全性靠token本身是不可猜的隨機字串，跟原本Flask版一致。
const app = initializeApp(firebaseConfig);
export const db = getFirestore(app);

const BATCH_SIZE = 10;
const LS_TOKEN_KEY = "taigi_verify_token";
const LS_NAME_KEY = "taigi_verify_name";

function safeName(name) {
  return name.trim();
}

export async function getOrCreateToken(name) {
  name = safeName(name);
  const tokenDocRef = doc(db, "taigi_tokens", name);
  const existing = await getDoc(tokenDocRef);
  let token;
  if (existing.exists()) {
    token = existing.data().token;
  } else {
    token = crypto.randomUUID();
    await setDoc(tokenDocRef, { token, createdAt: serverTimestamp() });
    await setDoc(doc(db, "taigi_reviews", token), { name, createdAt: serverTimestamp() });
  }
  localStorage.setItem(LS_TOKEN_KEY, token);
  localStorage.setItem(LS_NAME_KEY, name);
  return token;
}

export function getLocalSession() {
  const token = localStorage.getItem(LS_TOKEN_KEY);
  const name = localStorage.getItem(LS_NAME_KEY);
  return token && name ? { token, name } : null;
}

export function clearLocalSession() {
  localStorage.removeItem(LS_TOKEN_KEY);
  localStorage.removeItem(LS_NAME_KEY);
}

let DATA = null;
export async function loadData() {
  if (DATA) return DATA;
  const res = await fetch("./data.json");
  DATA = await res.json();
  return DATA;
}

export async function loadAnsweredIds(token) {
  const itemsCol = collection(db, "taigi_reviews", token, "items");
  const snap = await getDocs(itemsCol);
  return new Set(snap.docs.map((d) => d.id));
}

function sampleWithoutReplacement(arr, n) {
  const pool = [...arr];
  const out = [];
  for (let i = 0; i < n && pool.length > 0; i++) {
    const idx = Math.floor(Math.random() * pool.length);
    out.push(pool.splice(idx, 1)[0]);
  }
  return out;
}

export async function getOrInitBatch(token) {
  const parentRef = doc(db, "taigi_reviews", token);
  const parentSnap = await getDoc(parentRef);
  const data = await loadData();
  const answered = await loadAnsweredIds(token);

  const existingBatch = parentSnap.exists() ? parentSnap.data().currentBatch : null;
  if (existingBatch && existingBatch.length > 0) {
    return existingBatch;
  }
  const pool = data.filter((it) => !answered.has(it.id)).map((it) => it.id);
  if (pool.length === 0) return [];
  const batch = sampleWithoutReplacement(pool, BATCH_SIZE);
  await setDoc(parentRef, { currentBatch: batch, batchCreatedAt: serverTimestamp() }, { merge: true });
  return batch;
}

export async function startNewBatch(token) {
  const parentRef = doc(db, "taigi_reviews", token);
  const data = await loadData();
  const answered = await loadAnsweredIds(token);
  const pool = data.filter((it) => !answered.has(it.id)).map((it) => it.id);
  if (pool.length === 0) {
    await setDoc(parentRef, { currentBatch: [] }, { merge: true });
    return [];
  }
  const batch = sampleWithoutReplacement(pool, BATCH_SIZE);
  await setDoc(parentRef, { currentBatch: batch, batchCreatedAt: serverTimestamp() }, { merge: true });
  return batch;
}

export async function submitReview(token, itemId, payload) {
  const itemRef = doc(db, "taigi_reviews", token, "items", itemId);
  await setDoc(itemRef, { ...payload, reviewedAt: serverTimestamp() });
}

export function findItem(data, id) {
  return data.find((it) => it.id === id);
}

export const TOTAL_COUNT_PROMISE = loadData().then((d) => d.length);
