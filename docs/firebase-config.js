// 沿用英文單字網站的同一個Firebase專案，資料存在不同的collection
// (taigi_reviews / taigi_tokens)，不會跟單字網站的 users/* 資料衝突。
// 這組config是public client identifier，不是密鑰，安全靠Firestore規則
// 而不是隱藏這個檔案。
export const firebaseConfig = {
  projectId: "english-vocab-43160",
  appId: "1:146917438296:web:e79c9b2681c79ed5392b2d",
  storageBucket: "english-vocab-43160.firebasestorage.app",
  apiKey: "AIzaSyCEuKQ6250VXCbFntRJp7qg-STBmLwU8Z8",
  authDomain: "english-vocab-43160.firebaseapp.com",
  messagingSenderId: "146917438296",
};
