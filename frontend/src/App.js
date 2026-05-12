import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import QuizSetup from "@/pages/QuizSetup";
import QuizRun from "@/pages/QuizRun";
import QuizResults from "@/pages/QuizResults";
import TopicDetail from "@/pages/TopicDetail";
import Stats from "@/pages/Stats";

function App() {
    return (
        <div className="App">
            <BrowserRouter>
                <Routes>
                    <Route element={<Layout />}>
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/quiz/setup" element={<QuizSetup />} />
                        <Route path="/quiz/run" element={<QuizRun />} />
                        <Route path="/quiz/results" element={<QuizResults />} />
                        <Route path="/temas/:id" element={<TopicDetail />} />
                        <Route path="/stats" element={<Stats />} />
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
