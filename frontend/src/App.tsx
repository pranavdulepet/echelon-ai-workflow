import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function buildApiUrl(path: string) {
    if (!path.startsWith("/")) {
        path = `/${path}`;
    }
    if (!API_BASE_URL) {
        return path;
    }
    return `${API_BASE_URL}${path}`;
}

type Provider = "openai" | "anthropic";

type HistoryItem = {
    question: string;
    answer: string;
};

type CandidateForm = {
    id: string;
    title: string;
    slug: string;
};

type CandidateField = {
    id: string;
    label: string;
    code: string;
};

type ClarificationResponse = {
    type: "clarification";
    question: string;
    plan: unknown;
    reason?: string | null;
    form_candidates?: CandidateForm[];
    field_candidates?: CandidateField[];
};

type ChangeSetResponse = {
    type: "change_set";
    plan: unknown;
    change_set: Record<string, unknown>;
    before_snapshot?: Record<string, unknown> | null;
};

type ExplainResponse = {
    explanation: string;
};

type ApiResponse = ClarificationResponse | ChangeSetResponse;

type FormSummary = {
    id: string;
    slug: string;
    title: string;
    status: string;
};

type FormStructure = {
    form: Record<string, unknown>;
    pages: Array<Record<string, unknown>>;
    fields: Array<Record<string, unknown>>;
    options_by_field: Record<string, Array<Record<string, unknown>>>;
    logic_rules: Array<Record<string, unknown>>;
    logic_conditions: Array<Record<string, unknown>>;
    logic_actions: Array<Record<string, unknown>>;
};

type ActiveTab = "agent" | "database";

function App() {
    const [provider, setProvider] = useState<Provider>("openai");
    const [activeTab, setActiveTab] = useState<ActiveTab>("agent");

    const [query, setQuery] = useState("");
    const [rootQuery, setRootQuery] = useState<string | null>(null);
    const [history, setHistory] = useState<HistoryItem[]>([]);
    const [pendingClarification, setPendingClarification] = useState<string | null>(null);
    const [clarificationAnswer, setClarificationAnswer] = useState("");
    const [result, setResult] = useState<ApiResponse | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const [forms, setForms] = useState<FormSummary[]>([]);
    const [formsError, setFormsError] = useState<string | null>(null);
    const [isLoadingForms, setIsLoadingForms] = useState(false);
    const [selectedFormId, setSelectedFormId] = useState<string | null>(null);
    const [formStructure, setFormStructure] = useState<FormStructure | null>(null);
    const [isLoadingFormStructure, setIsLoadingFormStructure] = useState(false);
    const [formStructureError, setFormStructureError] = useState<string | null>(null);
    const [selectedDiffFormId, setSelectedDiffFormId] = useState<string | null>(null);
    const [isExplaining, setIsExplaining] = useState(false);
    const [explanation, setExplanation] = useState<string | null>(null);
    const [explainError, setExplainError] = useState<string | null>(null);
    const [copySuccess, setCopySuccess] = useState(false);
    const [fullscreenJson, setFullscreenJson] = useState<string | null>(null);

    const exampleQueries = [
        "update the dropdown options for the destination field in the travel request form: 1. add a paris option, 2. change tokyo to milan",
        "I want the employment-demo form to require university_name when employment_status is \"Student\". University name should be a text field",
        "I want to create a new form to allow employees to request a new snack. There should be a category field (ice cream/ beverage/ fruit/ chips/ gum), and name of the item (text)."
    ];

    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === "Escape" && fullscreenJson) {
                handleCloseFullscreen();
            }
        };
        window.addEventListener("keydown", handleEscape);
        return () => window.removeEventListener("keydown", handleEscape);
    }, [fullscreenJson]);

    async function callApi(currentQuery: string, currentHistory: HistoryItem[]) {
        setIsLoading(true);
        setError(null);
        try {
            const response = await fetch(buildApiUrl("/api/query"), {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    query: currentQuery,
                    provider,
                    history: currentHistory
                })
            });
            if (!response.ok) {
                const body = await response.json().catch(() => null);
                const message = body && body.detail ? String(body.detail) : "Request failed";
                throw new Error(message);
            }
            const data: ApiResponse = await response.json();
            setResult(data);
            if (data.type === "clarification") {
                setPendingClarification(data.question);
            } else {
                setPendingClarification(null);
                setClarificationAnswer("");
                if (data.before_snapshot && typeof data.before_snapshot === "object") {
                    const keys = Object.keys(data.before_snapshot);
                    setSelectedDiffFormId(keys.length > 0 ? keys[0] : null);
                } else {
                    setSelectedDiffFormId(null);
                }
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : "Unknown error";
            setError(message);
        } finally {
            setIsLoading(false);
        }
    }

    function handleSubmit(event: React.FormEvent) {
        event.preventDefault();
        if (!query.trim() || isLoading) {
            return;
        }
        setRootQuery(query.trim());
        setHistory([]);
        setResult(null);
        setPendingClarification(null);
        setClarificationAnswer("");
        setExplanation(null);
        setExplainError(null);
        callApi(query.trim(), []);
    }

    function submitClarification(answer: string) {
        if (!pendingClarification || !answer.trim() || isLoading) {
            return;
        }
        const updatedHistory = [
            ...history,
            { question: pendingClarification, answer: answer.trim() }
        ];
        setHistory(updatedHistory);
        setClarificationAnswer("");
        callApi(rootQuery || query, updatedHistory);
    }

    function handleClarificationSubmit(event: React.FormEvent) {
        event.preventDefault();
        if (!clarificationAnswer.trim()) {
            return;
        }
        submitClarification(clarificationAnswer);
    }

    function handleStartOver() {
        setQuery("");
        setRootQuery(null);
        setHistory([]);
        setResult(null);
        setPendingClarification(null);
        setClarificationAnswer("");
        setExplanation(null);
        setExplainError(null);
        setError(null);
        setSelectedDiffFormId(null);
    }

    function handleCopyJson() {
        if (result && result.type === "change_set") {
            const json = JSON.stringify(result.change_set, null, 2);
            navigator.clipboard.writeText(json).then(() => {
                setCopySuccess(true);
                setTimeout(() => setCopySuccess(false), 2000);
            }).catch(() => {
                setError("Failed to copy to clipboard");
            });
        }
    }

    function handleExampleClick(exampleQuery: string) {
        setQuery(exampleQuery);
    }

    function renderFormPreview(snapshot: any, changeSet: any, isAfter: boolean) {
        if (!snapshot || !snapshot.form) {
            return <div className="preview-empty">No form data available</div>;
        }

        const form = snapshot.form;
        const fields = snapshot.fields || [];
        const optionsByField: Record<string, any[]> = snapshot.options_by_field || {};

        // Apply changes if this is the "after" preview
        let modifiedFields = [...fields];
        let modifiedOptions = { ...optionsByField };

        if (isAfter && changeSet) {
            // Apply field changes
            if (changeSet.form_fields) {
                // Handle inserts
                if (changeSet.form_fields.insert) {
                    for (const field of changeSet.form_fields.insert) {
                        modifiedFields.push({
                            id: field.id,
                            code: field.code,
                            label: field.label,
                            type_key: field.type_id ? `type_${field.type_id}` : 'unknown',
                            required: field.required || 0,
                            placeholder: field.placeholder || null,
                            _isNew: true
                        });
                    }
                }
                // Handle updates
                if (changeSet.form_fields.update) {
                    for (const update of changeSet.form_fields.update) {
                        const idx = modifiedFields.findIndex(f => f.id === update.id);
                        if (idx !== -1) {
                            modifiedFields[idx] = { ...modifiedFields[idx], ...update, _isModified: true };
                        }
                    }
                }
                // Handle deletes
                if (changeSet.form_fields.delete) {
                    for (const del of changeSet.form_fields.delete) {
                        const idx = modifiedFields.findIndex(f => f.id === del.id);
                        if (idx !== -1) {
                            modifiedFields[idx] = { ...modifiedFields[idx], _isDeleted: true };
                        }
                    }
                }
            }

            // Apply option changes
            if (changeSet.option_items) {
                modifiedOptions = { ...modifiedOptions };
                // Handle inserts
                if (changeSet.option_items.insert) {
                    for (const opt of changeSet.option_items.insert) {
                        const fieldId = fields.find((f: any) =>
                            optionsByField[f.id]?.[0]?.option_set_id === opt.option_set_id
                        )?.id;
                        if (fieldId) {
                            if (!modifiedOptions[fieldId]) {
                                modifiedOptions[fieldId] = [];
                            }
                            modifiedOptions[fieldId].push({ ...opt, _isNew: true });
                        }
                    }
                }
                // Handle updates
                if (changeSet.option_items.update) {
                    for (const update of changeSet.option_items.update) {
                        for (const fieldId in modifiedOptions) {
                            const idx = modifiedOptions[fieldId].findIndex(o => o.id === update.id);
                            if (idx !== -1) {
                                modifiedOptions[fieldId][idx] = {
                                    ...modifiedOptions[fieldId][idx],
                                    ...update,
                                    _isModified: true
                                };
                            }
                        }
                    }
                }
            }
        }

        return (
            <div className="form-preview">
                <div className="form-preview-header">
                    <div className="form-preview-title">{form.title}</div>
                    <div className="form-preview-meta">{form.slug}</div>
                </div>
                <div className="form-preview-fields">
                    {modifiedFields.filter(f => !f._isDeleted).map((field, idx) => {
                        const options = modifiedOptions[field.id] || [];
                        const fieldClasses = [
                            'form-preview-field',
                            field._isNew && 'field-new',
                            field._isModified && 'field-modified',
                        ].filter(Boolean).join(' ');

                        return (
                            <div key={field.id || idx} className={fieldClasses}>
                                <div className="field-preview-header">
                                    <label className="field-preview-label">
                                        {field.label}
                                        {field.required === 1 && <span className="field-required">*</span>}
                                    </label>
                                    {field._isNew && <span className="field-badge badge-new">NEW</span>}
                                    {field._isModified && <span className="field-badge badge-modified">MODIFIED</span>}
                                </div>
                                {field.type_key && field.type_key.includes('text') && (
                                    <input
                                        type="text"
                                        className="field-preview-input"
                                        placeholder={field.placeholder || `Enter ${field.label.toLowerCase()}`}
                                        disabled
                                    />
                                )}
                                {field.type_key && (field.type_key.includes('dropdown') || field.type_key.includes('select')) && (
                                    <select className="field-preview-select" disabled>
                                        <option>Select an option</option>
                                        {options.filter(o => o.is_active !== 0).map(opt => {
                                            const optClasses = [
                                                opt._isNew && 'option-new',
                                                opt._isModified && 'option-modified',
                                            ].filter(Boolean).join(' ');
                                            return (
                                                <option key={opt.id} className={optClasses}>
                                                    {opt.label}
                                                    {opt._isNew && ' (NEW)'}
                                                    {opt._isModified && ' (MODIFIED)'}
                                                </option>
                                            );
                                        })}
                                    </select>
                                )}
                                {field.code && (
                                    <div className="field-preview-code">{field.code}</div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    }

    function handleExpandJson(value: unknown, label: string) {
        const text = JSON.stringify(value, null, 2);
        setFullscreenJson(JSON.stringify({ label, content: text }));
    }

    function handleCloseFullscreen() {
        setFullscreenJson(null);
    }

    function renderJson(value: unknown, label?: string, showExpand = true) {
        if (!value) {
            return null;
        }
        const text = JSON.stringify(value, null, 2);
        return (
            <div className="json-container">
                {showExpand && (
                    <button
                        type="button"
                        className="json-expand-button"
                        onClick={() => handleExpandJson(value, label || "JSON")}
                        title="Expand to fullscreen"
                    >
                        ⛶
                    </button>
                )}
                <pre className="json-block">{text}</pre>
            </div>
        );
    }

    async function loadForms() {
        setIsLoadingForms(true);
        setFormsError(null);
        try {
            const response = await fetch(buildApiUrl("/api/forms"));
            if (!response.ok) {
                throw new Error("Unable to load forms.");
            }
            const data: FormSummary[] = await response.json();
            setForms(data);
            if (!selectedFormId && data.length > 0) {
                setSelectedFormId(data[0].id);
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to load forms.";
            setFormsError(message);
        } finally {
            setIsLoadingForms(false);
        }
    }

    async function loadFormStructure(formId: string) {
        setIsLoadingFormStructure(true);
        setFormStructureError(null);
        try {
            const response = await fetch(buildApiUrl(`/api/forms/${encodeURIComponent(formId)}`));
            if (!response.ok) {
                throw new Error("Unable to load form details.");
            }
            const data: FormStructure = await response.json();
            setFormStructure(data);
        } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to load form details.";
            setFormStructureError(message);
        } finally {
            setIsLoadingFormStructure(false);
        }
    }

    useEffect(() => {
        if (activeTab === "database" && forms.length === 0 && !isLoadingForms) {
            loadForms();
        }
    }, [activeTab]);

    useEffect(() => {
        if (activeTab === "database" && selectedFormId) {
            loadFormStructure(selectedFormId);
        }
    }, [activeTab, selectedFormId]);

    function renderAgentTab() {
        const clarification = result && result.type === "clarification" ? result : null;
        const changeSetResult = result && result.type === "change_set" ? result : null;
        const beforeSnapshot =
            changeSetResult && changeSetResult.before_snapshot && typeof changeSetResult.before_snapshot === "object"
                ? changeSetResult.before_snapshot
                : null;

        const diffFormIds = beforeSnapshot ? Object.keys(beforeSnapshot) : [];
        const activeDiffFormId = selectedDiffFormId && diffFormIds.includes(selectedDiffFormId)
            ? selectedDiffFormId
            : diffFormIds[0] ?? null;

        function buildFormScopedChangeSet(
            changeSet: Record<string, any>,
            formId: string | null
        ): Record<string, any> | null {
            if (!formId) {
                return null;
            }
            const scoped: Record<string, any> = {};
            for (const [tableName, ops] of Object.entries(changeSet)) {
                const insertRows = Array.isArray((ops as any).insert) ? (ops as any).insert : [];
                const updateRows = Array.isArray((ops as any).update) ? (ops as any).update : [];
                const deleteRows = Array.isArray((ops as any).delete) ? (ops as any).delete : [];

                const filterRows = (rows: any[]) =>
                    rows.filter((row) => {
                        if (!row || typeof row !== "object") {
                            return false;
                        }
                        if (typeof row.form_id === "string" && row.form_id === formId) {
                            return true;
                        }
                        if (tableName === "forms" && typeof row.id === "string" && row.id === formId) {
                            return true;
                        }
                        return false;
                    });

                const scopedInsert = filterRows(insertRows);
                const scopedUpdate = filterRows(updateRows);
                const scopedDelete = filterRows(deleteRows);

                if (scopedInsert.length || scopedUpdate.length || scopedDelete.length) {
                    scoped[tableName] = {
                        insert: scopedInsert,
                        update: scopedUpdate,
                        delete: scopedDelete
                    };
                }
            }
            return Object.keys(scoped).length ? scoped : null;
        }

        const scopedChangeSet =
            changeSetResult && activeDiffFormId
                ? buildFormScopedChangeSet(changeSetResult.change_set as Record<string, any>, activeDiffFormId)
                : null;

        async function handleExplain() {
            if (!changeSetResult) {
                return;
            }
            setIsExplaining(true);
            setExplainError(null);
            try {
                const response = await fetch(buildApiUrl("/api/explain"), {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        query: rootQuery || query,
                        plan: changeSetResult.plan,
                        change_set: changeSetResult.change_set,
                        provider
                    })
                });
                if (!response.ok) {
                    const body = await response.json().catch(() => null);
                    const message = body && body.detail ? String(body.detail) : "Request failed";
                    throw new Error(message);
                }
                const data: ExplainResponse = await response.json();
                setExplanation(data.explanation);
            } catch (err) {
                const message = err instanceof Error ? err.message : "Failed to explain plan.";
                setExplainError(message);
            } finally {
                setIsExplaining(false);
            }
        }

        async function handleExplainStream() {
            if (!changeSetResult) {
                return;
            }
            setIsExplaining(true);
            setExplainError(null);
            setExplanation("");
            try {
                const response = await fetch(buildApiUrl("/api/explain/stream"), {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        query: rootQuery || query,
                        plan: changeSetResult.plan,
                        change_set: changeSetResult.change_set,
                        provider
                    })
                });
                if (!response.ok || !response.body) {
                    const body = await response.json().catch(() => null);
                    const message = body && body.detail ? String(body.detail) : "Request failed";
                    throw new Error(message);
                }
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let fullText = "";
                while (true) {
                    const { value, done } = await reader.read();
                    if (done) {
                        break;
                    }
                    const chunk = decoder.decode(value, { stream: true });
                    fullText += chunk;
                    setExplanation(prev => (prev ?? "") + chunk);
                }
                setExplanation(fullText);
            } catch (err) {
                const message = err instanceof Error ? err.message : "Failed to explain plan.";
                setExplainError(message);
            } finally {
                setIsExplaining(false);
            }
        }

        return (
            <>
                {!result && !isLoading && (
                    <div className="examples-section">
                        <p className="examples-label">Try an example:</p>
                        <div className="examples-grid">
                            {exampleQueries.map((example, index) => (
                                <button
                                    key={index}
                                    type="button"
                                    className="example-button"
                                    onClick={() => handleExampleClick(example)}
                                >
                                    <span className="example-number">{index + 1}</span>
                                    <span className="example-text">{example}</span>
                                </button>
                            ))}
                        </div>
                    </div>
                )}

                <form onSubmit={handleSubmit} className="query-form">
                    <label className="field-label" htmlFor="query">
                        Request
                    </label>
                    <textarea
                        id="query"
                        className="query-input"
                        rows={4}
                        placeholder="Example: update the dropdown options for the destination field in the travel request form..."
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                    <div className="query-toolbar">
                        {error && <span className="inline-error">{error}</span>}
                        <button type="submit" className="primary-button" disabled={isLoading}>
                            {isLoading ? (
                                <span className="loading-content">
                                    Processing...
                                </span>
                            ) : (
                                "Generate change"
                            )}
                        </button>
                        {(result || history.length > 0) && (
                            <button
                                type="button"
                                className="secondary-button"
                                onClick={handleStartOver}
                                disabled={isLoading}
                            >
                                Clear
                            </button>
                        )}
                    </div>
                </form>

                {isLoading && (
                    <div className="loading-panel">
                        <div className="loading-spinner-large"></div>
                        <div className="loading-text">
                            <div className="loading-title">Analyzing your request...</div>
                            <div className="loading-subtitle">
                                The AI is reading the database schema and planning changes
                            </div>
                        </div>
                    </div>
                )}

                {pendingClarification && clarification && !isLoading && (
                    <section className="clarification-section">
                        <div className="clarification-header">
                            <div>
                                <h2 className="section-title">Need more information</h2>
                                <p className="clarification-subtitle">Please help clarify your request</p>
                            </div>
                        </div>

                        <div className="clarification-question-box">
                            <p className="clarification-question">{pendingClarification}</p>
                        </div>

                        {(clarification.form_candidates && clarification.form_candidates.length > 0) && (
                            <div className="clarification-choices">
                                <p className="clarification-help">
                                    <strong>Choose a form:</strong>
                                </p>
                                <div className="clarification-buttons">
                                    {clarification.form_candidates.map((form) => (
                                        <button
                                            key={form.id}
                                            type="button"
                                            className="choice-button"
                                            onClick={() =>
                                                submitClarification(
                                                    `Use form "${form.title}" with slug ${form.slug}`
                                                )
                                            }
                                            disabled={isLoading}
                                        >
                                            <span className="choice-title">{form.title}</span>
                                            <span className="choice-meta">{form.slug}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {(clarification.field_candidates && clarification.field_candidates.length > 0) && (
                            <div className="clarification-choices">
                                <p className="clarification-help">
                                    <strong>Choose a field:</strong>
                                </p>
                                <div className="clarification-buttons">
                                    {clarification.field_candidates.map((field) => (
                                        <button
                                            key={field.id}
                                            type="button"
                                            className="choice-button"
                                            onClick={() =>
                                                submitClarification(
                                                    `Use field "${field.label}" with code ${field.code}`
                                                )
                                            }
                                            disabled={isLoading}
                                        >
                                            <span className="choice-title">{field.label}</span>
                                            <span className="choice-meta">{field.code}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {(!clarification.form_candidates?.length && !clarification.field_candidates?.length) && (
                            <form onSubmit={handleClarificationSubmit} className="clarification-form">
                                <label className="field-label" htmlFor="clarification">
                                    <strong>Your answer:</strong>
                                </label>
                                <input
                                    id="clarification"
                                    type="text"
                                    className="clarification-input"
                                    placeholder="Type your answer here..."
                                    value={clarificationAnswer}
                                    onChange={(e) => setClarificationAnswer(e.target.value)}
                                    disabled={isLoading}
                                    autoFocus
                                />
                                <button type="submit" className="secondary-button" disabled={isLoading || !clarificationAnswer.trim()}>
                                    {isLoading ? (
                                        <span className="loading-content">
                                            <span className="loading-spinner"></span>
                                            Sending...
                                        </span>
                                    ) : (
                                        "Submit answer"
                                    )}
                                </button>
                            </form>
                        )}

                        {(clarification.form_candidates?.length || clarification.field_candidates?.length) ? (
                            <div className="clarification-or-divider">
                                <span>or provide a different answer</span>
                            </div>
                        ) : null}

                        {(clarification.form_candidates?.length || clarification.field_candidates?.length) ? (
                            <form onSubmit={handleClarificationSubmit} className="clarification-form-secondary">
                                <input
                                    type="text"
                                    className="clarification-input-small"
                                    placeholder="Type a custom answer..."
                                    value={clarificationAnswer}
                                    onChange={(e) => setClarificationAnswer(e.target.value)}
                                    disabled={isLoading}
                                />
                                <button type="submit" className="tertiary-button" disabled={isLoading || !clarificationAnswer.trim()}>
                                    Submit
                                </button>
                            </form>
                        ) : null}
                    </section>
                )}

                {history.length > 0 && (
                    <section className="history-section">
                        <h2 className="section-title">Clarifications</h2>
                        <ul className="history-list">
                            {history.map((item, index) => (
                                <li key={index} className="history-item">
                                    <div className="history-question">Q: {item.question}</div>
                                    <div className="history-answer">A: {item.answer}</div>
                                </li>
                            ))}
                        </ul>
                    </section>
                )}

                {changeSetResult && (
                    <section className="result-section">
                        <div className="result-header">
                            <h2 className="section-title">Planned change</h2>
                            <div className="result-actions">
                                <button
                                    type="button"
                                    className="secondary-button"
                                    onClick={handleCopyJson}
                                >
                                    {copySuccess ? "✓ Copied!" : "Copy JSON"}
                                </button>
                                <button
                                    type="button"
                                    className="secondary-button"
                                    onClick={handleExplainStream}
                                    disabled={isExplaining}
                                >
                                    {isExplaining ? "Explaining…" : "Explain"}
                                </button>
                            </div>
                        </div>
                        {renderJson(changeSetResult.change_set, "Change-set JSON")}
                    </section>
                )}

                {result && result.type === "clarification" && (
                    <section className="result-section">
                        <h2 className="section-title">Current plan</h2>
                        {renderJson(result.plan, "Intent Plan JSON")}
                    </section>
                )}

                {explanation && (
                    <section className="result-section">
                        <h2 className="section-title">Explanation</h2>
                        <div className="explanation-content">
                            <ReactMarkdown>{explanation}</ReactMarkdown>
                        </div>
                    </section>
                )}

                {explainError && (
                    <section className="error-section">
                        <p className="error-text">{explainError}</p>
                    </section>
                )}

                {changeSetResult && beforeSnapshot && diffFormIds.length > 0 && (
                    <section className="result-section">
                        <h2 className="section-title">Visual Preview</h2>
                        <div className="diff-header">
                            <label className="field-label" htmlFor="diff-form">
                                Select Form
                            </label>
                            <select
                                id="diff-form"
                                className="provider-input"
                                value={activeDiffFormId ?? ""}
                                onChange={(e) => setSelectedDiffFormId(e.target.value || null)}
                            >
                                {diffFormIds.map((id) => {
                                    const snapshot: any = (beforeSnapshot as any)[id];
                                    const title = snapshot && snapshot.form && snapshot.form.title
                                        ? String(snapshot.form.title)
                                        : id;
                                    return (
                                        <option key={id} value={id}>
                                            {title}
                                        </option>
                                    );
                                })}
                            </select>
                        </div>
                        <div className="preview-layout">
                            <div className="preview-column">
                                <div className="preview-column-header">
                                    <h3 className="preview-column-title">Current State</h3>
                                    <span className="preview-column-badge">Before</span>
                                </div>
                                {activeDiffFormId && renderFormPreview((beforeSnapshot as any)[activeDiffFormId], null, false)}
                            </div>
                            <div className="preview-divider">
                                <div className="preview-arrow">→</div>
                            </div>
                            <div className="preview-column">
                                <div className="preview-column-header">
                                    <h3 className="preview-column-title">After Changes</h3>
                                    <span className="preview-column-badge badge-after">After</span>
                                </div>
                                {activeDiffFormId && renderFormPreview((beforeSnapshot as any)[activeDiffFormId], scopedChangeSet ?? changeSetResult.change_set, true)}
                            </div>
                        </div>
                        <details className="preview-json-details">
                            <summary className="preview-json-summary">Show JSON (Technical Details)</summary>
                            <div className="diff-layout">
                                <div className="diff-column">
                                    <h3 className="db-subtitle">Current</h3>
                                    {activeDiffFormId && renderJson((beforeSnapshot as any)[activeDiffFormId], "Current State")}
                                </div>
                                <div className="diff-column">
                                    <h3 className="db-subtitle">Planned changes</h3>
                                    {renderJson(scopedChangeSet ?? changeSetResult.change_set, "Planned Changes")}
                                </div>
                            </div>
                        </details>
                    </section>
                )}
            </>
        );
    }

    function renderDatabaseTab() {
        return (
            <div className="db-layout">
                <div className="db-sidebar">
                    <div className="db-sidebar-header">
                        <h2 className="section-title">Forms</h2>
                        {isLoadingForms && <span className="db-hint">Loading…</span>}
                    </div>
                    {formsError && <div className="error-text">{formsError}</div>}
                    <ul className="db-form-list">
                        {forms.map((form) => (
                            <li key={form.id}>
                                <button
                                    type="button"
                                    className={
                                        selectedFormId === form.id ? "db-form-button db-form-button-active" : "db-form-button"
                                    }
                                    onClick={() => setSelectedFormId(form.id)}
                                >
                                    <span className="db-form-title">{form.title}</span>
                                    <span className="db-form-slug">{form.slug}</span>
                                </button>
                            </li>
                        ))}
                    </ul>
                </div>
                <div className="db-content">
                    {!selectedFormId && <div className="db-placeholder">Select a form to inspect its structure.</div>}

                    {selectedFormId && (
                        <>
                            <div className="db-content-header">
                                <h2 className="section-title">Form structure</h2>
                                {isLoadingFormStructure && <span className="db-hint">Loading…</span>}
                            </div>
                            {formStructureError && <div className="error-text">{formStructureError}</div>}

                            {formStructure && (
                                <>
                                    <div className="db-section">
                                        <h3 className="db-subtitle">Overview</h3>
                                        <div className="db-overview-row">
                                            <span className="db-overview-label">Title</span>
                                            <span className="db-overview-value">{String(formStructure.form.title ?? "")}</span>
                                        </div>
                                        <div className="db-overview-row">
                                            <span className="db-overview-label">Slug</span>
                                            <span className="db-overview-value">{String(formStructure.form.slug ?? "")}</span>
                                        </div>
                                        <div className="db-overview-row">
                                            <span className="db-overview-label">Status</span>
                                            <span className="db-overview-value">{String(formStructure.form.status ?? "")}</span>
                                        </div>
                                    </div>

                                    <div className="db-section">
                                        <h3 className="db-subtitle">Pages and fields</h3>
                                        <div className="db-columns">
                                            <div className="db-column">
                                                <h4 className="db-column-title">Pages</h4>
                                                <ul className="db-simple-list">
                                                    {formStructure.pages.map((page) => (
                                                        <li key={String(page.id)}>
                                                            <span className="db-pill">
                                                                #{String(page.position)} {String(page.title ?? "(untitled page)")}
                                                            </span>
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                            <div className="db-column">
                                                <h4 className="db-column-title">Fields</h4>
                                                <ul className="db-field-list">
                                                    {formStructure.fields.map((field) => {
                                                        const fieldId = String(field.id);
                                                        const options = formStructure.options_by_field[fieldId] || [];
                                                        return (
                                                            <li key={fieldId} className="db-field-item">
                                                                <div className="db-field-main">
                                                                    <span className="db-field-label">{String(field.label)}</span>
                                                                    <span className="db-field-meta">
                                                                        {String(field.code)} · {String(field.field_type_key)}
                                                                        {field.required ? " · required" : ""}
                                                                    </span>
                                                                </div>
                                                                {options.length > 0 && (
                                                                    <div className="db-field-options">
                                                                        {options.map((opt) => (
                                                                            <span key={String(opt.id)} className="db-pill">
                                                                                {String(opt.label)}
                                                                            </span>
                                                                        ))}
                                                                    </div>
                                                                )}
                                                            </li>
                                                        );
                                                    })}
                                                </ul>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="db-section">
                                        <h3 className="db-subtitle">Raw JSON</h3>
                                        {renderJson(formStructure, "Form Structure JSON")}
                                    </div>
                                </>
                            )}
                        </>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div className="app-root">
            <div className="app-card">
                <header className="app-header">
                    <div>
                        <h1 className="app-title">Form Agent</h1>
                        <p className="app-subtitle">
                            Plan database changes for your forms, and inspect the underlying structure.
                        </p>
                    </div>
                    <div className="provider-select">
                        <label className="provider-label" htmlFor="provider">
                            Model
                        </label>
                        <select
                            id="provider"
                            value={provider}
                            onChange={(e) => setProvider(e.target.value as Provider)}
                            className="provider-input"
                        >
                            <option value="openai">OpenAI</option>
                            <option value="anthropic">Claude</option>
                        </select>
                    </div>
                </header>

                <div className="app-tabs">
                    <button
                        type="button"
                        className={activeTab === "agent" ? "tab-button tab-button-active" : "tab-button"}
                        onClick={() => setActiveTab("agent")}
                    >
                        Agent
                    </button>
                    <button
                        type="button"
                        className={activeTab === "database" ? "tab-button tab-button-active" : "tab-button"}
                        onClick={() => setActiveTab("database")}
                    >
                        Database
                    </button>
                </div>

                <main className="app-main">
                    {activeTab === "agent" ? renderAgentTab() : renderDatabaseTab()}
                </main>
            </div>

            {fullscreenJson && (() => {
                const parsed = JSON.parse(fullscreenJson);
                return (
                    <div className="fullscreen-overlay" onClick={handleCloseFullscreen}>
                        <div className="fullscreen-modal" onClick={(e) => e.stopPropagation()}>
                            <div className="fullscreen-header">
                                <h2 className="fullscreen-title">{parsed.label}</h2>
                                <button
                                    type="button"
                                    className="fullscreen-close"
                                    onClick={handleCloseFullscreen}
                                    title="Close (Esc)"
                                >
                                    ✕
                                </button>
                            </div>
                            <pre className="fullscreen-json">{parsed.content}</pre>
                        </div>
                    </div>
                );
            })()}
        </div>
    );
}

export default App;


