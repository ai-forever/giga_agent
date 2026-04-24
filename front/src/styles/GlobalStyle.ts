import { createGlobalStyle } from "styled-components";

export const GlobalStyle = createGlobalStyle`
    
    .markdown p {
        margin: 0;
    }
    .markdown a {
        text-decoration: underline;
        cursor: pointer;
    }
    
    .img-hidden {
        display: none !important;
    }
`;
