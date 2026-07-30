import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import SubjectDetail from "@/pages/SubjectDetail";
import QuizSetup from "@/pages/QuizSetup";
import QuizRun from "@/pages/QuizRun";
import QuizResults from "@/pages/QuizResults";
import TopicDetail from "@/pages/TopicDetail";
import Stats from "@/pages/Stats";
import FlashcardMode from "@/pages/FlashcardMode";
import SurvivalMode from "@/pages/SurvivalMode";
import Account from "@/pages/Account";
import Uso from "@/pages/Uso";
import Biblioteca from "@/pages/Biblioteca";
import Library from "@/pages/Library";
import QuestionBank from "@/pages/QuestionBank";
import LibrarySummaries from "@/pages/LibrarySummaries";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import ProtectedRoute from "@/components/ProtectedRoute";
import { AuthProvider } from "@/context/AuthContext";

function App() {
    return (
        <div className="App">
            <BrowserRouter>
                <AuthProvider>
                    <Routes>
                        {/* Rutas públicas */}
                        <Route path="/login" element={<Login />} />
                        <Route path="/register" element={<Register />} />
                        {/* Rutas protegidas: requieren sesión */}
                        <Route element={<ProtectedRoute />}>
                            <Route element={<Layout />}>
                                <Route path="/" element={<Dashboard />} />
                                <Route path="/asignaturas/:id" element={<SubjectDetail />} />
                                <Route path="/quiz/setup" element={<QuizSetup />} />
                                <Route path="/quiz/run" element={<QuizRun />} />
                                <Route path="/quiz/results" element={<QuizResults />} />
                                <Route path="/temas/:id" element={<TopicDetail />} />
                                <Route path="/stats" element={<Stats />} />
                                {/* Biblioteca: página paraguas con pestañas (PDFs · Preguntas · Resúmenes) */}
                                <Route path="/biblioteca" element={<Biblioteca />}>
                                    <Route index element={<Navigate to="/biblioteca/pdfs" replace />} />
                                    <Route path="pdfs" element={<Library />} />
                                    <Route path="preguntas" element={<QuestionBank />} />
                                    <Route path="resumenes" element={<LibrarySummaries />} />
                                </Route>
                                {/* Compat: el antiguo /preguntas ahora vive dentro de Biblioteca */}
                                <Route path="/preguntas" element={<Navigate to="/biblioteca/preguntas" replace />} />
                                <Route path="/temas/:id/flashcards" element={<FlashcardMode />} />
                                <Route path="/supervivencia" element={<SurvivalMode />} />
                                <Route path="/cuenta" element={<Account />} />
                                <Route path="/uso" element={<Uso />} />
                            </Route>
                        </Route>
                    </Routes>
                </AuthProvider>
            </BrowserRouter>
            <Toaster
                position="top-right"
                toastOptions={{
                    style: {
                        background: "#ffffff",
                        border: "1px solid #E6E2D8",
                        color: "#23211F",
                    },
                }}
            />
        </div>
    );
}

export default App;
