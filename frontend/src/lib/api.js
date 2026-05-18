import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

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
