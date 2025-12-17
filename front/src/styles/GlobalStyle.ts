import { createGlobalStyle } from "styled-components";

export const GlobalStyle = createGlobalStyle`
    
    .markdown p {
        margin: 0;
    }
    .markdown a {
        text-decoration: underline;
        cursor: pointer;
    }
    
    thinking {
            font-size: 0.7rem;
    font-style: italic;
    color: gray;
            display: block;
    line-height: 1.2rem;
    margin-bottom: 0.5rem;
    }
    
    thinking:before {
        content: "Рассуждения: ";
    }
    
    .img-hidden {
        display: none !important;
    }
`;
