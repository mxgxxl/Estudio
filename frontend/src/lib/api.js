import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

// --- Auth token storage ---
const TOKEN_KEY = "studia_token";
export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// Adjunta "Authorization: Bearer <token>" a TODAS las peticiones automáticamente.
api.interceptors.request.use((config) => {
    const token = getToken();
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
});

// Detecta las URLs de acciones que consumen cuota de IA (para refrescar el
// contador tras una generación correcta).
const AI_GEN_URL_RE = /(\/topics\/upload|\/regenerate|\/generate|\/summary|\/eval-dev)$/;

api.interceptors.response.use(
    (r) => {
        // Tras una generación de IA correcta, avisa para refrescar el contador.
        const method = (r?.config?.method || "").toLowerCase();
        const url = r?.config?.url || "";
        if (method === "post" && AI_GEN_URL_RE.test(url)) {
            window.dispatchEvent(new CustomEvent("studia:ai-generated"));
        }
        return r;
    },
    (error) => {
        const status = error?.response?.status;
        // 401: sesión caducada/ inválida -> limpiar token y mandar a /login.
        if (status === 401) {
            clearToken();
            if (!window.location.pathname.startsWith("/login")) {
                window.location.assign("/login");
            }
        }
        // 402: sin cuota de IA. NO cierra sesión (sigue autenticado). Avisamos a
        // la UI para mostrar el aviso de "hazte Premium".
        if (status === 402) {
            window.dispatchEvent(
                new CustomEvent("studia:quota-exceeded", {
                    detail: error?.response?.data?.detail || "",
                })
            );
        }
        return Promise.reject(error);
    }
);

// --- Auth API ---
export const register = (email, password) =>
    api.post("/auth/register", { email, password }).then((r) => r.data);
export const login = (email, password) =>
    api.post("/auth/login", { email, password }).then((r) => r.data);
export const getMe = () => api.get("/auth/me").then((r) => r.data);

// Uso de IA (contador de generaciones del mes para el plan del usuario)
export const getUsage = () => api.get("/usage/me").then((r) => r.data);

// Billing (Paddle)
export const billingCheckout = () => api.post("/billing/checkout").then((r) => r.data);
export const billingStatus = () => api.get("/billing/status").then((r) => r.data);
export const billingPortal = () => api.post("/billing/portal").then((r) => r.data);

// Subjects
export const listSubjects = () => api.get("/subjects").then((r) => r.data);
export const createSubject = (data) => api.post("/subjects", data).then((r) => r.data);
export const getSubject = (id) => api.get(`/subjects/${id}`).then((r) => r.data);
export const updateSubject = (id, data) => api.patch(`/subjects/${id}`, data).then((r) => r.data);
export const deleteSubject = (id) => api.delete(`/subjects/${id}`).then((r) => r.data);
export const listSubjectTopics = (id) => api.get(`/subjects/${id}/topics`).then((r) => r.data);

// Topics (global)
export const listTopics = () => api.get("/topics").then((r) => r.data);
export const getTopic = (id) => api.get(`/topics/${id}`).then((r) => r.data);
export const deleteTopic = (id) => api.delete(`/topics/${id}`).then((r) => r.data);
export const getTopicQuestions = (id) => api.get(`/topics/${id}/questions`).then((r) => r.data);
export const getTopicPdfs = (id) => api.get(`/topics/${id}/pdfs`).then((r) => r.data);

export const uploadTopic = (subjectId, formData) =>
    api
        .post(`/subjects/${subjectId}/topics/upload`, formData, {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 300000,
        })
        .then((r) => r.data);

// PDFs
export const regenerateFromPdf = (pdfId, payload) =>
    api.post(`/pdfs/${pdfId}/regenerate`, payload, { timeout: 300000 }).then((r) => r.data);
export const deletePdf = (pdfId) => api.delete(`/pdfs/${pdfId}`).then((r) => r.data);
export const addPdfToTopic = (topicId, formData) =>
    api
        .post(`/topics/${topicId}/pdfs/upload`, formData, {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 120000,
        })
        .then((r) => r.data);
export const generateFromTopicPdfs = (topicId, payload) =>
    api.post(`/topics/${topicId}/generate`, payload, { timeout: 300000 }).then((r) => r.data);

// Questions
export const toggleFavorite = (qid) => api.post(`/questions/${qid}/favorite`).then((r) => r.data);
export const toggleDifficult = (qid) => api.post(`/questions/${qid}/difficult`).then((r) => r.data);
export const deleteQuestion = (qid) => api.delete(`/questions/${qid}`).then((r) => r.data);

// Quiz
export const quizStart = (payload) => api.post("/quiz/start", payload).then((r) => r.data);
export const quizSubmit = (payload) => api.post("/quiz/submit", payload).then((r) => r.data);

// Stats
export const getStats = () => api.get("/stats").then((r) => r.data);
export const getStatsBySubject = () => api.get("/stats/by-subject").then((r) => r.data);
export const getStatsByTopic = () => api.get("/stats/by-topic").then((r) => r.data);

// Questions edit
export const editQuestion = (qid, data) => api.patch(`/questions/${qid}`, data).then((r) => r.data);

// Topic text (for study mode)
export const getTopicText = (topicId) => api.get(`/topics/${topicId}/text`).then((r) => r.data);

// Dev question eval
export const evalDevAnswer = (payload) => api.post("/quiz/eval-dev", payload).then((r) => r.data);

// Flashcards
export const getTopicFlashcards = (topicId) => api.get(`/topics/${topicId}/flashcards`).then((r) => r.data);
export const generateTopicFlashcards = (topicId, numCards = 15) =>
    api.post(`/topics/${topicId}/flashcards/generate?num_cards=${numCards}`, {}, { timeout: 120000 }).then((r) => r.data);
export const reviewFlashcard = (cardId, correct) =>
    api.post(`/flashcards/${cardId}/review?correct=${correct}`).then((r) => r.data);
export const toggleFlashcardFavorite = (cardId) => api.post(`/flashcards/${cardId}/favorite`).then((r) => r.data);
export const deleteFlashcard = (cardId) => api.delete(`/flashcards/${cardId}`).then((r) => r.data);

// Survival records
export const getSurvivalRecords = () => api.get("/survival/records").then((r) => r.data);
export const getSurvivalRecord = (scopeType, scopeId) => api.get(`/survival/records/${scopeType}/${scopeId}`).then((r) => r.data);
export const saveSurvivalRecord = (data) => api.post("/survival/records", data).then((r) => r.data);

// AI Summary
export const generateTopicSummary = (topicId) => api.post(`/topics/${topicId}/summary`, {}, { timeout: 120000 }).then((r) => r.data);

// Gap detector
export const getKnowledgeGaps = () => api.get("/stats/gaps").then((r) => r.data);
