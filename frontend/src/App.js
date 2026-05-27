import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
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

function App() {
    return (
        <div className="App">
            <BrowserRouter>
                <Routes>
                    <Route element={<Layout />}>
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/asignaturas/:id" element={<SubjectDetail />} />
                        <Route path="/quiz/setup" element={<QuizSetup />} />
                        <Route path="/quiz/run" element={<QuizRun />} />
                        <Route path="/quiz/results" element={<QuizResults />} />
                        <Route path="/temas/:id" element={<TopicDetail />} />
                        <Route path="/stats" element={<Stats />} />
                        <Route path="/temas/:id/flashcards" element={<FlashcardMode />} />
                        <Route path="/supervivencia" element={<SurvivalMode />} />
                    </Route>
                </Routes>
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
