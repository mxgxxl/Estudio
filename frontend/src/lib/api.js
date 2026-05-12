import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export async function listTopics() {
    const { data } = await api.get("/topics");
    return data;
}

export async function uploadTopic(formData) {
    const { data } = await api.post("/topics/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 300000,
    });
    return data;
}

export async function addMoreToTopic(topicId, formData) {
    const { data } = await api.post(`/topics/${topicId}/generate-more`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 300000,
    });
    return data;
}

export async function deleteTopic(id) {
    const { data } = await api.delete(`/topics/${id}`);
    return data;
}

export async function getTopicQuestions(id) {
    const { data } = await api.get(`/topics/${id}/questions`);
    return data;
}

export async function toggleFavorite(qid) {
    const { data } = await api.post(`/questions/${qid}/favorite`);
    return data;
}

export async function toggleDifficult(qid) {
    const { data } = await api.post(`/questions/${qid}/difficult`);
    return data;
}

export async function deleteQuestion(qid) {
    const { data } = await api.delete(`/questions/${qid}`);
    return data;
}

export async function quizStart(payload) {
    const { data } = await api.post("/quiz/start", payload);
    return data;
}

export async function quizSubmit(payload) {
    const { data } = await api.post("/quiz/submit", payload);
    return data;
}

export async function getStats() {
    const { data } = await api.get("/stats");
    return data;
}

export async function getStatsByTopic() {
    const { data } = await api.get("/stats/by-topic");
    return data;
}
